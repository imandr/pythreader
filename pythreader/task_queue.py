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
        
class TaskQueue(Primitive):
    
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

    def __init__(self, nworkers=None, capacity=None, stagger=0.0, tasks = [], delegate=None, 
                        name=None):
        """Initializes the TaskQueue object
        
        Args:
            nworkers (int): maximum number of tasks to be executed concurrently. Default: no limit.
            capacity (int): maxinum number of tasks allowed in the queue before they start. If the capacity is reached, append() and insert() methods
                        will block. Default: no limit.

        Keyword Arguments:
            stagger (int or float): time interval in seconds between consecutive task starts. Default=0, no staggering.
            tasks (list of Task objects): initial task list to be added to the queue
            delegate (object): an object to receive callbacks with task status updates. If None, updates will not be sent.
            name (string): PyThreader object name
            daemon (boolean): Threading daemon flag for the queue internal thread. Default = True

            common_attributes (dict): attributes to attach to each file, will be overridden by the individual file attribute values with the same key
            project_attributes (dict): attriutes to attach to the new project
            query (str): query used to create the file list, optional. If specified, the query string will be added to the project as the attribute.
        """
        Primitive.__init__(self, name=name)
        self.NWorkers = nworkers
        self.Threads = []
        self.Queue = DEQueue(capacity)
        self.Held = False
        self.Stagger = stagger
        self.LastStart = 0.0
        self.StartTimer = None
        self.Delegate = delegate
        self.Stop = False
        for t in tasks:
            self.addTask(t)
        
    def stop(self):
        """Stops the queue thread"""
        self.Stop = True
        self.Queue.close()
        self.cancel_alarm()
        
    def __add(self, mode, task, *params,
            timeout=None, promise_data=None, after=None, force=False, **args):
        if not isinstance(task, Task):
            if callable(task):
                task = FunctionTask(task, *params, **args)
            else:
                raise ArgumentError("The task argument must be either a callable or a Task subclass instance")
        timeout = timeout.total_seconds() if isinstance(timeout, timedelta) else timeout
        if isinstance(after, timedelta):
            after = after.totalseconds()
        if after is not None and after < 10*365*24*3600:            # ~ Jan 1 1980
            after = time.time() + after
        task._Private.After = after.timestamp() if isinstance(after, datetime) else after
        task._Private.Promise = promise = Promise(data=promise_data)
        with self:
            if mode == "insert":
                self.Queue.insert(task, timeout = timeout, force=force)
            else:           # mode == "append"
                self.Queue.append(task, timeout = timeout, force=force)
        task._queued()
        self.start_tasks()
        return promise

    def append(self, task, *params, timeout=None, promise_data=None, after=None, force=False, **args):
        """Appends the task to the end of the queue. If the queue is at or above its capacity, the method will block.
        
        Args:
            task (Task): A Task subclass instance to be added to the queue

        Keyword Arguments:
            timeout (int or float or timedelta): time to block if the queue is at or above the capacity. Default: block indefinitely.
            promise_data (object): data to be associated with the task's promise
            after (int or float or datetime): time to start the task after. 
                If ``after`` is numeric and < 365 days or it is a datetime.timedelta object, it is interpreted as time relative to the current time.
                Default: start as soon as possible
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
                If ``after`` is numeric and < 365 days or it is a datetime.timedelta object, it is interpreted as time relative to the current time.
                Default: start as soon as possible
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

    @synchronized
    def start_tasks(self):
        again = True
        while not self.Held and not self.Stop and again:
            again = False
            now = time.time()
            if self.Stagger is not None and self.LastStart + self.Stagger > now:
                self.alarm(self.start_tasks, t = self.LastStart + self.Stagger)
            elif self.Queue:
                nrunning = len(self.Threads)
                if (self.NWorkers is None or nrunning < self.NWorkers):
                    next_task = None
                    sleep_until = None
                    for t in self.Queue.items():
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
                        again = True
                    elif sleep_until is not None:
                        self.alarm(self.start_tasks, t=sleep_until)

    @synchronized
    def threadEnded(self, t):
        #print("queue.threadEnded: ", t)
        if t in self.Threads:
            self.Threads.remove(t)
        task = t.Task
        if task.Resubmit:
            after = None if task.ResubmitInterval is None else task.Queued + task.ResubmitInterval
            self.add(task, after=after, force=True)
        self.start_tasks()
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
        self.start_tasks()
        
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

    @synchronized
    def cancel(self, task):
        """
        Cancel a queued task. Can be used only of the task was added as a Task object. The Promise associated with the Task will be
        fulfilled with None as the result. If the queue has a delegate, the taskCancelled delegate's method will be called.
        If the task was already runnig or was not found in the queue, ValueError exception will be raised.

        Args:
            task (Task): A Task subclass instance
        
        Returns:
            Task: cancelled task
        """

        try:    self.Queue.remove(task)
        except ValueError:
            raise ValueError("Task not in the queue")
        task._Private.Promise.complete()
        self.call_delegate("taskCancelled", self, task)
        self.start_tasks()
        return task

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
