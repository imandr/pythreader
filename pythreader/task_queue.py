import time, traceback, sys
from datetime import datetime, timedelta
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
        
class _TaskPrivate(object):
    pass

class Task(Primitive):
    
    Resubmit = False
    ResubmitInterval = None

    def __init__(self, name=None):
        Primitive.__init__(self, name=name)
        self.Created = time.time()
        self.Queued = None
        self.Started = None
        self.Ended = None
        # used by the TaskQueue
        self._Private = _TaskPrivate()
        self._Private.After = None
        self._Private.Promise = None
        
    @property
    def _promise(self):
        return self._Private.Promise
    
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
        
    def _started(self):
        self.Started = time.time()
        
    def _ended(self):
        self.Ended = time.time()
        
    def _queued(self):
        self.Queued = time.time()

    def __rshift__(self, queue):
        if not isinstance(queue, TaskQueue):
            raise TypeError(f"unsupported operand type(s) for >>: 'Task' and %s" % (type(queue),))
        return queue.insert(self)

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
        
class TaskQueue(PyThread):
    
    class ExecutorThread(PyThread):
        def __init__(self, queue, task):
            PyThread.__init__(self, daemon=True)
            self.Queue = queue
            self.Task = task
            
        def run(self):
            task = self.Task
            task._started()
            try:
                if callable(task):
                    result = task()
                else:
                    result = task.run()
                task._ended()
                promise = task._Private.Promise
                if promise is not None:
                    promise.complete(result)
                self.Queue.taskEnded(self.Task, result)
            except:
                exc_type, value, tb = sys.exc_info()
                task._ended()
                promise = task._Private.Promise
                if promise is not None:
                    promise.exception(exc_type, value, tb)
                self.Queue.taskFailed(self.Task, exc_type, value, tb)
            finally:
                self.Queue.threadEnded(self)
                self.Queue = None
                task._Private.Promise = None

    def __init__(self, nworkers=None, capacity=None, stagger=None, tasks = [], delegate=None, 
                        name=None, daemon=True, start_immediately=True):
        """Initializes the TaskQueue object
        
        Args:
            nworkers (int): maximum number of tasks to be executed concurrently. Default: no limit.
            capacity (int): maxinum number of tasks allowed in the queue before they start. If the capacity is reached, append() and insert() methods
                        will block. Default: no limit.

        Keyword Arguments:
            stagger (int or float): time interval in seconds between consecutive task starts. None or 0 means no staggering.
            tasks (list of Task objects): initial task list to be added to the queue
            delegate (object): an object to receive callbacks with task status updates. If None, updates will not be sent.
            name (string): PyThreader object name
            daemon (boolean): Threading daemon flag for the queue internal thread. Default = True

            common_attributes (dict): attributes to attach to each file, will be overridden by the individual file attribute values with the same key
            project_attributes (dict): attriutes to attach to the new project
            query (str): query used to create the file list, optional. If specified, the query string will be added to the project as the attribute.
        """
        PyThread.__init__(self, name=name, daemon=daemon)
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
        self.Stop = False
        if start_immediately:
            self.start()
        
    def stop(self):
        """Stops the queue thread"""
        self.Stop = True
        self.wakeup()
        
    def make_task(self, task_or_callable, *params, **args):
        if isinstance(task_or_callable, Task):
            # params and args are ignored
            task = task_or_callable
        elif callable(task_or_callable):
            task = FunctionTask(task_or_callable, *params, **args)
        else:
            raise ArgumentError("The task argument must be either a callable or a Task subclass instance")
        return task
            
    def __add(self, mode, task, *params,
            timeout=None, promise_data=None, after=None, force=False, **args):
        task = self.make_task(task, *params, **args)
        timeout = timeout.total_seconds() if isinstance(timeout, timedelta) else timeout
        task._Private.After = after.timestamp() if isinstance(after, datetime) else after
        if mode == "insert":
            self.Queue.insert(task, timeout = timeout, force=force)
        else:           # mode == "append"
            self.Queue.append(task, timeout = timeout, force=force)
        task._queued()
        task._Private.Promise = promise = Promise(data=promise_data)
        self.wakeup()
        return promise

    def append(self, task, *params, timeout=None, promise_data=None, after=None, force=False, **args):
        """Appends the task to the end of the queue. If the queue is at or above its capacity, the method will block.
        
        Args:
            task (Task): A Task subclass instance to be added to the queue

        Keyword Arguments:
            timeout (int or float or timedelta): time to block if the queue is at or above the capacity. Default: block indefinitely.
            promise_data (object): data to be associated with the task's promise
            after (int or float or datetime): time to start the task after. Default: start as soon as possible
            force (boolean): ignore the queue capacity and append the task immediately. Default: False
        
        Returns:
            Promise: promise object associated with the task. The Promise will be delivered when the task ends.

        Raises:
            RuntimeError: the queue is closed or the timeout expired
        """
        return self.__add("append", task, *params, 
                after=after, timeout=timeout, promise_data=promise_data, force=force, **args)
        
    add = addTask = append
        
    def __iadd__(self, task):
        return self.addTask(task)

    def insert(self, task, *params, timeout = None, promise_data=None, after=None, force=False, **args):
        """Inserts the task at the beginning of the queue. If the queue is at or above its capacity, the method will block.
           A Task can be also inserted into the queue using the '>>' operator. In this case, '>>' operator returns
           the promise object associated with the task: ``promise = task >> queue``.
        
        Args:
            task (Task): A Task subclass instance to be added to the queue

        Keyword Arguments:
            timeout (int or float or timedelta): time to block if the queue is at or above the capacity. Default: block indefinitely.
            promise_data (object): data to be associated with the task's promise
            after (int or float or datetime): time to start the task after. Default: start as soon as possible
            force (boolean): ignore the queue capacity and append the task immediately. Default: False
        
        Returns:
            Promise: promise object associated with the task. The Promise will be delivered when the task ends.
        
        Raises:
            RuntimeError: the queue is closed or the timeout expired
        """
        return self.__add("insert", task, *params, 
                after=after, timeout=timeout, promise_data=promise_data, force=force, **args)
        
    insertTask = insert

    def __lshift__(self, task):
        """Allows to append the task using the '<<' operator: ``promise = queue << task``.
        
        Returns:
            Promise: promise object associated with the task. The Promise will be delivered when the task ends.
        """
        return self.append(task)

    def run(self):
        while not self.Stop:
            with self:
                now = time.time()
                if self.Stagger is not None and self.LastStart + self.Stagger > now:
                    self.sleep(self.LastStart + self.Stagger - now)
                elif self.Queue \
                            and (self.NWorkers is None or len(self.Threads) < self.NWorkers) \
                            and not self.Held:
                    queued = self.Queue.items()
                    next_task = None
                    sleep_until = None
                    for t in queued:
                        after = t._Private.After
                        if after is None or after <= now:
                            next_task = t
                            break
                        else:
                            sleep_until = after if sleep_until is None else min(sleep_until, after)
                    if next_task is not None:
                        self.Queue.remove(next_task)
                        t = self.ExecutorThread(self, next_task)
                        t.kind = "%s.task" % (self.kind,)
                        self.Threads.append(t)
                        self.call_delegate("taskIsStarting", self, next_task)
                        self.LastStart = time.time()
                        t.start()
                        self.call_delegate("taskStarted", self, next_task)
                    else:
                        now = time.time()
                        if now < sleep_until:
                            self.sleep(sleep_until - now)
                else:
                    self.sleep(10)

    @synchronized
    def threadEnded(self, t):
        #print("queue.threadEnded: ", t)
        if t in self.Threads:
            self.Threads.remove(t)
        task = t.Task
        if task.Resubmit:
            after = None if task.ResubmitInterval is None else task.Queued + task.ResubmitInterval
            self.add(task, after=after, force=True)
        self.wakeup()
        
    def call_delegate(self, cb, *params):
        if self.Delegate is not None and hasattr(self.Delegate, cb):
            try:    
                return getattr(self.Delegate, cb)(*params)
            except:
                traceback.print_exc(file=sys.stderr)
            
    def taskEnded(self, task, result):
        return self.call_delegate("taskEnded", self, task, result)
        
    def taskFailed(self, task, exc_type, exc_value, tb):
        if self.Delegate is None:
            print("Exception in task:", task)
            traceback.print_exception(exc_type, exc_value, tb, file=sys.stderr)
        else:
            return self.call_delegate("taskFailed", self, task,  exc_type, exc_value, tb)
            
    @synchronized
    def waitingTasks(self):
        """
        Returns:
            list: the list of tasks waiting in the queue
        """
        return list(self.Queue.items())
        
    @synchronized
    def activeTasks(self):
        """
        Returns:
            list: the list of running tasks
        """
        return [t.Task for t in self.Threads]
        
    @synchronized
    def tasks(self):
        """
        Returns:
            tuple: (self.waitingTasks(), self.activeTasks())
        """
        return self.waitingTasks(), self.activeTasks()
        
    def nrunning(self):
        """
        Returns:
            int: number of runnign tasks
        """
        return len(self.Threads)
        
    def nwaiting(self):
        """
        Returns:
            int: number of waiting tasks
        """
        return len(self.Queue)
        
    @synchronized
    def counts(self):
        """
        Returns:
            tuple: (self.nwaiting(), self.nrunning())
        """
        return self.nwaiting(), self.nrunning()
        
    @synchronized
    def hold(self):
        """
        Holds the queue, preventing new tasks from being started
        """
        self.Held = True
        
    @synchronized
    def release(self):
        """
        Releses the queue, allowing new tasks to start
        """        
        self.Held = False
        self.wakeup()
        
    @synchronized
    def is_empty(self):
        """
        Returns:
            bollean: True if no tasks are running and no tasks are waiting
        """
        return len(self.Queue) == 0 and len(self.Threads) == 0
        
    isEmpty = is_empty
    
    @synchronized
    def waitUntilEmpty(self):
        """
        Blocks until the queue is empty (no tasks are running and no tasks are waiting)
        """
        # wait until all tasks are done and the queue is empty
        if not self.isEmpty():
            while not self.sleep(function=self.isEmpty):
                pass
                
    join = waitUntilEmpty

    def drain(self):
        """
        Holds the queue and then blocks until the queue is empty (no tasks are running and no tasks are waiting)
        """
        self.hold()
        self.waitUntilEmpty()

    @synchronized
    def flush(self):
        """
        Discards all waiting tasks
        """
        self.Queue.flush()
        self.wakeup()
            
    def __len__(self):
        """
        Equivalent to TaskQueue.nwaiting()
        """
        return len(self.Queue)

    def __contains__(self, item):
        """
        Returns true if the task is in the queue and is waiting.
        """
        return item in self.Queue
