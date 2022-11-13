from .core import Primitive, synchronized
from .dequeue import DEQueue
from .task_queue import Task, TaskQueue
from .promise import Promise
import sys, traceback

class _WorkerTask(Task):
    
    def __init__(self, processor, item, promise):
        Task.__init__(self)
        self.Processor = processor
        self.Item = item
        self.Promise = promise
        
    def run(self):
        out = self.Processor._process(self.Item, self.self.Promise)
            
class _OutputIterator(object):
    
    def __init__(self, processor, queue):
        self.Queue = queue
        self.Processor = processor
        
    def __next__(self):
        try:    out, exc_info = self.Queue.pop()
        except StopIteration:
            self.Processor._remove_output_queue(self.Queue)
            raise
        if exc_info:
            _, e, _ = exc_info
            raise e
        else:
            return out
            
    def __del__(self):
        self.Processor._remove_output_queue(self.Queue)
        

class Processor(Primitive):
    
    def __init__(self, max_workers = None, queue_capacity = None, name=None, output = None, stagger=None, delegate=None,
            put_timeout=None):
        Primitive.__init__(self, name=name)
        self.Output = output or DEQueue()
        self.WorkerQueue = TaskQueue(max_workers, capacity=queue_capacity, stagger=stagger)
        self.Delegate = delegate
        self.PutTimeout = put_timeout
        self.Closed = True
        
    def hold(self):
        self.WorkerQueue.hold()

    def release(self):
        self.WorkerQueue.release()

    def close(self):
        self.Closed = True
        self.WorkerQueue.close()

    def put(self, item, timeout=-1):
        if timeout == -1: timeout = self.PutTimeout
        promise = Promise()
        self.WorkerQueue.addTask(_WorkerTask(self, item, promise), timeout)
        return promise

    def get(self):
        return self.Output.get()

    def join(self):
        return self.WorkerQueue.join()

    def _process(self, item, promise):
        #print("%x: Processor._process: item: %s" % (id(self), item))
        try:    
            out = self.process(item)
        except:
            exc_type, exc_value, tb = sys.exc_info()
            if self.Delegate is not None:
                self.Delegate.itemFailed(item, exc_type, exc_value, tb)
            raise
            promise.exception(exc_type, exc_value, tb)
            if self.OutputQueue is not None:
                self.OutputQueue.append((None, (exc_type, exc_value, tb)))
        else:
            #print("%x: out: %s" % (id(self), out))
            if self.Delegate is not None:
                self.Delegate.itemProcessed(item, out)
            if self.Output is not None and out is not None:
                    next_promise = self.Output.put(out)
                    if next_promise is not None:
                        # fulfil this promise later, when the output processor has done with the item
                        next_promise.Name = "secondary"
                        next_promise.chain(promise)
                        return
            promise.complete(out)

    def process(self, item):
        # override me
        pass
        
    def waitingTasks(self):
        return self.WorkerQueue.waitingTasks()
        
    def activeTasks(self):
        return self.WorkerQueue.activeTasks()
        
    def tasks(self):
        return self.WorkerQueue.tasks()
        
    def nrunning(self):
        return self.WorkerQueue.nrunning()
        
    def nwaiting(self):
        return self.WorkerQueue.nwaiting()
        
    def counts(self):
        return self.WorkerQueue.counts()
        
    @synchronized
    def __iter__(self):
        return iter(self.Output)
