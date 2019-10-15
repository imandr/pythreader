import time
from .core import Primitive, PyThread, synchronized
from .dequeue import DEQueue
from threading import Timer

class Task(Primitive):

    def __init__(self):
        Primitive.__init__(self)
        self._t_Started = None
        self._t_Ended = None
    
    #def __call__(self):
    #    pass

    def run(self):
        raise NotImplementedError
        
    @synchronized
    @property
    def started(self):
        return self._t_Started is not None
        
    @synchronized
    @property
    def running(self):
        return self._t_Started is not None and self._t_Ended is None
        
    @synchronized
    @property
    def ended(self):
        return self._t_Started is not None and self._t_Ended is not None
        
    @synchronized
    def start(self):
        self._t_Started = time.time()
        
    @synchronized
    def end(self):
        self._t_Ended = time.time()

class FunctionTask(Task):

    def __init__(self, fcn, *params, **args):
        Task.__init__(self)
        self.F = fcn
        self.Params = params
        self.Args = args
        
    def run(self):
        return self.F(*self.Params, **self.Args)
        
    
class TaskQueue(Primitive):
    
    class ExecutorThread(PyThread):
        def __init__(self, queue, task):
            PyThread.__init__(self)
            self.Queue = queue
            self.Task = task
            
        def run(self):
            task = self.Task
            task.start()
            try:
                if callable(task):
                    task()
                else:
                    task.run()
            finally:
                task.end()
                self.Queue.threadEnded(self)
                self.Queue = None
                    
    def __init__(self, nworkers, capacity=None, stagger=0.0, tasks = []):
        Primitive.__init__(self)
        self.NWorkers = nworkers
        self.Threads = []
        self.Queue = DEQueue(capacity)
        self.Held = False
        self.Stagger = stagger
        self.LastStart = 0.0
        self.StartTimer = None
        for t in tasks:
            self.addTask(t)

    def addTask(self, task, timeout = None):
        #print "addTask() entry"
        self.Queue.append(task, timeout=timeout)
        #print "queue.append done"
        self.startThreads()
        return self
        
    def __iadd__(self, task):
        return self.addTask(task)
        
    def __lshift__(self, task):
        return self.addTask(task)
        
    def insertTask(self, task, timeout = None):
        self.Queue.insert(task, timeout = timeout)
        self.startThreads()
        return self
        
    def __rrshift__(self, task):
        return self.insertTask(task)
        
    @synchronized
    def armStartTimer(self):
        def fire():
            #print "fire() entry"
            with self:
                self.StartTimer = None
                #print "fire: calling startThreads..."
                self.startThreads()
                #print "fire: done"
        if self.StartTimer is None:
            delta = max(0.0, self.LastStart + self.Stagger - time.time())
            self.StartTimer = Timer(delta, fire)
            self.StartTimer.start()
        else:
            #print "timer already armed"
            pass
        
        
    @synchronized
    def startThreads(self):
        #print "startThreads() entry"
        if not self.Held:
            while self.Queue and len(self.Threads) < self.NWorkers and not self.Held:
                if self.Stagger > 0.0 and time.time() < self.LastStart + self.Stagger:
                    #print "arming timer..."
                    self.armStartTimer()
                    break
                else:
                    # start next thread
                    #print "staring thread..."
                    task = self.Queue.pop()
                    t = self.ExecutorThread(self, task)
                    t.kind = "%s.task" % (self.kind,)
                    self.Threads.append(t)
                    t.start()
                    self.LastStart = time.time()
        #print "startThreads() exit"
                   
            
    @synchronized
    def threadEnded(self, t):
        if t in self.Threads:
            self.Threads.remove(t)
        self.startThreads()
        self.wakeup()
            
    @synchronized
    def tasks(self):
        return list(self.Queue.items()), [t.Task for t in self.Threads]
        
    @synchronized
    def activeTasks(self):
        return [t.Task for t in self.Threads]
        
    @synchronized
    def waitingTasks(self):
        return list(self.Queue.items())
        
    
        
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
                
    def waitUntilEmpty(self):
        # wait until all tasks are done and the queue is empty
        if not self.isEmpty():
            while not self.sleep(function=self.isEmpty):
                pass
                
    def drain(self):
        self.hold()
        self.waitUntilEmpty()
                
    @synchronized
    def flush(self):
        self.Queue.flush()
        self.wakeup()
            
    def __len__(self):
        return len(self.Queue)

