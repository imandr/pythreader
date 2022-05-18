import time, traceback, sys
from .core import Primitive, PyThread, synchronized
from .dequeue import DEQueue
from .promise import Promise
from threading import Timer

class TaskQueueDelegate(object):
    
    # abstract class
    
    def taskIsStarting(self, queue, task):
        pass

    def taskStarted(self, queue, task):
        pass

    def taskEnded(self, queue, task, result):
        pass

    def taskFailed(self, queue, task, exc_type, exc_value, tback):
        pass

class Task(Primitive):

    def __init__(self, name=None, after=None):
        Primitive.__init__(self, name=name)
        self.Created = time.time()
        self.Queued = None
        self.Started = None
        self.Ended = None
        self._Promise = None
        self.After = after
    
    #def __call__(self):
    #    pass

    def run(self):
        raise NotImplementedError
        
    @property
    def has_started(self):
        return self.Started is not None
        
    @synchronized
    @property
    def is_running(self):
        return self.Started is not None and self.Ended is None
        
    @synchronized
    @property
    def has_ended(self):
        return self.Started is not None and self.Ended is not None
        
    def start(self):
        self.Started = time.time()
        
    def end(self):
        self.Ended = time.time()
        
    def enqueue(self):
        self.Queued = time.time()

class FunctionTask(Task):

    def __init__(self, fcn, *params, **args):
        Task.__init__(self)
        self.F = fcn
        self.Params = params
        self.Args = args
        
    def run(self):
        result = self.F(*self.Params, **self.Args)
        self.F = self.Params = self.Args = None
        return result

class TaskQueue(Primitive):
    
    class ExecutorThread(PyThread):
        def __init__(self, queue, task):
            PyThread.__init__(self, daemon=True)
            self.Queue = queue
            self.Task = task
            
        def run(self):
            task = self.Task
            task.start()
            try:
                if callable(task):
                    result = task()
                else:
                    result = task.run()
                task.end()
                self.Queue.taskEnded(self.Task, result)
                promise = task._Promise
                if promise is not None:
                    promise.complete(result)
            except:
                task.end()
                exc_type, value, tb = sys.exc_info()
                self.Queue.taskFailed(self.Task, exc_type, value, tb)
                promise = task._Promise
                if promise is not None:
                    promise.exception(exc_type, value, tb)
            finally:
                self.Queue.threadEnded(self)
                self.Queue = None
                task._Promise = None
                    
    def __init__(self, nworkers, capacity=None, stagger=None, tasks = [], delegate=None, name=None):
        Primitive.__init__(self, name=name)
        self.NWorkers = nworkers
        self.Threads = []
        self.Queue = DEQueue(capacity)
        self.Held = False
        self.Stagger = stagger or 0.0
        self.LastStart = 0.0
        self.StartTimer = None
        self.Delegate = delegate
        for t in tasks:
            self.addTask(t)

    @synchronized
    def addTask(self, task, timeout = None, after=None, promise_data=None):
        #print "addTask() entry"
        task.After = task.After or after
        self.Queue.append(task, timeout=timeout)
        #print("queue.append done", self.counts())
        task.enqueue()
        task._Promise = Promise(data=promise_data)
        self.startThreads()
        return task._Promise
        
    add = addTask
        
    def __iadd__(self, task):
        return self.addTask(task)
        
    def __lshift__(self, task):
        return self.addTask(task)
        
    def add_lambda(self, fcn, *params, timeout = None, after=None, promise_data=None, **kwargs):
        task = FunctionTask(fcn, *params, **kwargs)
        return self.addTask(task, timeout=timeout, after=after, promise_data=promise_data)
        
    @synchronized
    def insertTask(self, task, timeout = None, after=None, promise_data=None):
        task.After = task.After or after
        self.Queue.insert(task, timeout = timeout)
        task.enqueue()
        task._Promise = Promise(data=promise_data)
        self.startThreads()
        return task._Promise
        
    insert = insertTask

    def insert_lambda(self, fcn, *params, timeout = None, after=None, **kwargs):
        task = FunctionTask(fcn, *params, **kwargs)
        return self.insertTask(task, timeout=timeout, after=after, promise_data=promise_data)
        
    def __rshift__(self, task):
        return self.insertTask(task)
        
    @synchronized
    def timer_fired(self):
        self.StartTimer = None
        self.startThreads()
        
    @synchronized
    def arm_timer(self, t):
        if self.StartTimer is not None:
            self.StartTimer.cancel()
        delta = max(0.0, t - time.time())
        self.StartTimer = Timer(delta, self.timer_fired)
        self.StartTimer.daemon = True
        self.StartTimer.start()

    @synchronized
    def next_wakeup(self):
        """
        Returns time to start next task
        - returns now() if next task is ready to start
        - None if the queue is empty
        """
        tmin = None
        now = time.time()
        tasks = self.Queue.items()
        for task in tasks:
            t = task.After or now
            tmin = min(tmin or t, t)

        if tmin is not None and self.Stagger is not None:
            tmin = max(tmin, self.LastStart + self.Stagger)

        return tmin

    @synchronized
    def startThreads(self):
        #print "startThreads() entry"
        if not self.Held:
            while self.Queue \
                    and (self.NWorkers is None or len(self.Threads) < self.NWorkers) \
                    and not self.Held:

                if self.Stagger and time.time() < self.LastStart + self.Stagger:
                    break

                # find next task ready to start (time > task.After)
                for task in self.Queue.items():
                    if task.After is None or task.After < time.time():
                        self.Queue.remove(task)
                        break
                else:
                    task = None
                
                if task is not None:
                    self.LastStart = time.time()
                    t = self.ExecutorThread(self, task)
                    t.kind = "%s.task" % (self.kind,)
                    self.Threads.append(t)
                    self.call_delegate("taskIsStarting", self, task)
                    t.start()
                    self.call_delegate("taskStarted", self, task)
                    
            tnext = self.next_wakeup()
            if tnext is not None:
                self.arm_timer(tnext)

    @synchronized
    def threadEnded(self, t):
        #print("queue.threadEnded: ", t)
        if t in self.Threads:
            self.Threads.remove(t)
        self.startThreads()
        self.wakeup()
        
    def call_delegate(self, cb, *params):
        if self.Delegate is not None and hasattr(self.Delegate, cb):
            try:    getattr(self.Delegate, cb)(*params)
            except:
                traceback.print_exc(file=sys.stderr)
            
    def taskEnded(self, task, result):
        self.call_delegate("taskEnded", self, task, result)
        
    def taskFailed(self, task, exc_type, exc_value, tb):
        if self.Delegate is None:
            sys.stdout.write("Exception in task %s:\n" % (task, ))
            traceback.print_exception(exc_type, exc_value, tb, file=sys.stderr)
        else:
            self.call_delegate("taskFailed", self, task,  exc_type, exc_value, tb)
            
    @synchronized
    def waitingTasks(self):
        return list(self.Queue.items())
        
    @synchronized
    def activeTasks(self):
        return [t.Task for t in self.Threads]
        
    @synchronized
    def tasks(self):
        return self.waitingTasks(), self.activeTasks()
        
    def nrunning(self):
        return len(self.Threads)
        
    def nwaiting(self):
        return len(self.Queue)
        
    @synchronized
    def counts(self):
        return self.nwaiting(), self.nrunning()
        
    @synchronized
    def hold(self):
        self.Held = True
        
    @synchronized
    def release(self):
        self.Held = False
        self.startThreads()
        
    @synchronized
    def isEmpty(self):
        return len(self.Queue) == 0 and len(self.Threads) == 0
        
    is_empty = isEmpty
                
    def waitUntilEmpty(self):
        # wait until all tasks are done and the queue is empty
        if not self.isEmpty():
            while not self.sleep(function=self.isEmpty):
                pass
                
    join = waitUntilEmpty
                
    def drain(self):
        self.hold()
        self.waitUntilEmpty()
                
    @synchronized
    def flush(self):
        self.Queue.flush()
        self.wakeup()
            
    def __len__(self):
        return len(self.Queue)

    def __contains__(self, item):
        return item in self.Queue
