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
        
def _after_time(after):
    if after is None:   return None
    if isinstance(after, timedelta):
        after = time.time() + after.totalseconds()
    elif isinstance(after, datetime):
        after = after.timestamp()
    if after < 10*365*24*3600:  # 1980
        after = time.time() + after
    return after
    
def _time_interval(interval):
    if isinstance(interval, timedelta):
        interval = interval.totalseconds()
    return interval
        
class Task(Primitive):

    class _TaskPrivate(object):
        pass

    def __init__(self, name=None):
        Primitive.__init__(self, name=name)
        self.Created = time.time()
        self.Queued = None
        self.Started = None
        self.Ended = None
        # Use _Private member to avoid name clashes with a subclass
        self._Private = self._TaskPrivate()
        self._Private.Promise = None
        self._Private.RepeatInterval = None
        self._Private.RunCount = 1
        self._Private.After = None
        self._Private.Running = False               # True actually means that the Executor thread was created and about to be started
        self._Private.LastStart = None
        self._Private.Cancelled = False
        
    def __repr__(self):
        return str(self)
        
    @property
    def promise(self):
        return self._Private.Promise
        
    @synchronized
    def cancel(self):
        if not self._Private.Cancelled:
            self._Private.Cancelled = True
            promise = self._Private.Promise
            if promise is not None:
                promise.cancel()
            self._Private.Promise = None
            
    @property
    def is_cancelled(self):
        return self._Private.Cancelled

    @synchronized
    def repeat(self, after=None, count=1, interval=0):
        if not self._Private.Cancelled:
            self._Private.RunCount = count
            self._Private.RepeatInterval = _time_interval(interval)
            self._Private.After = _after_time(after)

    def run(self):
        raise NotImplementedError
        
    @property
    def has_started(self):
        return self.Started is not None
        
    @property
    @synchronized
    def is_running(self):
        return self._Private.Running
        
    @synchronized
    def to_be_repeated(self):
        interval = self._Private.RepeatInterval
        count = self._Private.RunCount
        repeat = interval is not None and (count is None or count > 0) \
            or interval is None and count is not None and count > 0
        return repeat and self.should_repeat()

    @property
    @synchronized
    def has_ended(self):
        return self.Started and not self.is_running and not self.to_be_repeated()

    @synchronized
    def _started(self):
        t = time.time()
        if self.Started is None:    self.Started = t
        if self._Private.RunCount is not None:
            self._Private.RunCount -= 1
        self._Private.LastStart = t
        self._Private.LastEnd = None

    @synchronized
    def _ended(self):
        self._Private.LastEnd = self.Ended = time.time()
        
    def _queued(self):
        self.Queued = time.time()

    def __rshift__(self, queue):
        if not isinstance(queue, TaskQueue):
            raise TypeError(f"unsupported operand type(s) for >>: 'Task' and %s" % (type(queue),))
        return queue.insert(self)

    # overridable
    
    def should_repeat(self):
        return True



class FunctionTask(Task):

    def __init__(self, fcn, *params, **args):
        Task.__init__(self)
        self.F = fcn
        self.Params = params
        self.Args = args
        
    def run(self):
        result = self.F(*self.Params, **self.Args)
        #self.F = self.Params = self.Args = None
        return result
        
class TaskQueue(Primitive):
    
    class ExecutorThread(PyThread):
        def __init__(self, queue, task):
            PyThread.__init__(self, daemon=True)
            self.Queue = queue
            self.Task = task
            task._Private.Running = True
            
        def run(self):
            task = self.Task
            task._started()             # this will decrement RunCount
            repeat = False
            try:
                if callable(task):
                    result = task()
                else:
                    result = task.run()
                task._ended()
                #print(task._Private.__dict__)
                repeat = task.to_be_repeated() \
                    and self.Queue.taskWillRepeat(task, result, task._Private.After, task._Private.RunCount) is not False
                #print("repeat:", repeat)
                if repeat:
                    interval = task._Private.RepeatInterval or 0
                    task._Private.After = (task._Private.LastStart if task._Private.After is None else task._Private.After) + interval
                else:
                    promise = task._Private.Promise
                    if promise is not None:
                        promise.complete(result)
                        task._Private.Promise = None
                    self.Queue.taskEnded(task, result)
            except:
                exc_type, value, tb = sys.exc_info()
                traceback.print_exc()
                task._ended()
                promise = task._Private.Promise
                if promise is not None:
                    promise.exception(exc_type, value, tb)
                self.Queue.taskFailed(self.Task, exc_type, value, tb)
            finally:
                task._Private.Running = False
                self.Queue.threadEnded(task, repeat)
                self.Queue = None

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
            timeout=None, promise_data=None, force=False,
            count = None, interval = None, after=None,
            **args):

        if interval is None and count is None:
            count = 1
        
        if not isinstance(task, Task):
            if callable(task):
                task = FunctionTask(task, *params, **args)
            else:
                raise ArgumentError("The task argument must be either a callable or a Task subclass instance")

        task._Private.Promise = promise = Promise(data=promise_data)

        task._Private.RunCount = count
        task._Private.RepeatInterval = _time_interval(interval)
        task._Private.After = _after_time(after)

        with self:
            if mode == "insert":
                self.Queue.insert(task, timeout = timeout, force=force)
            else:           # mode == "append"
                self.Queue.append(task, timeout = timeout, force=force)
        task._queued()
        self.start_tasks()
        return promise

    def reinsert_task(self, task):
        self.Queue.insert(task, force=True)

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
        wakeup = False
        # remove cancelled
        for t in self.Queue.items():
            if t.is_cancelled:
                self.Queue.remove(t)
                wakeup = True
        again = True
        while not self.Held and not self.Stop and again:
            again = False
            now = time.time()
            if self.Stagger is not None and self.LastStart + self.Stagger > now:
                self.alarm(self.start_tasks, t = self.LastStart + self.Stagger)
            elif self.Queue:
                nrunning = self.nrunning()
                if (self.NWorkers is None or nrunning < self.NWorkers):
                    next_task = None
                    sleep_until = None
                    waiting_tasks = self.waitingTasks()
                    for t in self.waitingTasks():
                        after = t._Private.After
                        if after is None or after <= now:
                            next_task = t
                            break
                        else:
                            sleep_until = after if sleep_until is None else min(sleep_until, after)
                    if next_task is not None:
                        do_wakeup = True
                        t = self.ExecutorThread(self, next_task)
                        t.kind = "%s.task" % (self.kind,)
                        self.LastStart = time.time()
                        self.call_delegate("taskIsStarting", self, next_task, t)
                        t.start()
                        self.call_delegate("taskStarted", self, next_task, t)
                        again = True
                    elif sleep_until is not None:
                        self.alarm(self.start_tasks, t=sleep_until)
        if wakeup:
            self.wakeup()
        

    def threadEnded(self, task, repeat):
        if not repeat:
            self.Queue.remove(task)
            self.wakeup()
        self.start_tasks()
        
    def call_delegate(self, cb, *params):
        if self.Delegate is not None and hasattr(self.Delegate, cb):
            try:    
                return getattr(self.Delegate, cb)(*params)
            except:
                traceback.print_exc(file=sys.stderr)
            
    def taskEnded(self, task, result):
        return self.call_delegate("taskEnded", self, task, result)
        
    def taskWillRepeat(self, task, result, next_t, count):
        return self.call_delegate("taskWillRepeat", self, task, result, next_t, count)
        
    def taskFailed(self, task, exc_type, exc_value, tb):
        return self.call_delegate("taskFailed", self, task,  exc_type, exc_value, tb)
            
    def waitingTasks(self):
        """
        Returns:
            list: the list of tasks waiting in the queue
        """
        return [t for t in self.Queue.items() if not t.is_running]
        
    @synchronized
    def activeTasks(self):
        """
        Returns:
            list: the list of running tasks
        """
        return [t for t in self.Queue.items() if t.is_running]
        
    @synchronized
    def tasks(self):
        """
        Returns:
            tuple: (self.waitingTasks(), self.activeTasks())
        """
        tasks = self.Queue.items()
        return [t for t in tasks if not t.is_running], [t for t in tasks if t.is_running]
        
    def nrunning(self):
        """
        Returns:
            int: number of runnign tasks
        """
        return sum(t.is_running for t in self.Queue.items())
        
    def nwaiting(self):
        """
        Returns:
            int: number of waiting tasks
        """
        return sum(not t.is_running for t in self.Queue.items())
        
    def counts(self):
        """
        Returns:
            tuple: (self.nwaiting(), self.nrunning())
        """
        nrunning, nwaiting = 0, 0
        for t in self.Queue.items():
            if t.is_running:    nrunning += 1
            else:               nwaiting += 1
        return nwaiting, nrunning
        
    def hold(self):
        """
        Holds the queue, preventing new tasks from being started
        """
        self.Held = True
        
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
        return len(self.Queue) == 0
        
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


class _Delegate(object):
    
    def task_failed(self, queue, task, exc_type, exc_value, tb):
        traceback.print_exception(exc_type, exc_value, tb, file=sys.stderr)

_GlobalTaskQueue = TaskQueue(delegate = _Delegate())

del _Delegate

def schedule_task(fcn, *params, **args):
    return _GlobalTaskQueue.append(fcn, *params, **args)
