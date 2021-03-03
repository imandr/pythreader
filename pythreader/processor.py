from .core import Primitive, synchronized
from .dequeue import DEQueue
from .task_queue import Task, TaskQueue
import sys, traceback

class _WorkerTask(Task):
    
    def __init__(self, processor, item, promise):
        Task.__init__(self)
        self.Processor = processor
        self.Item = item
        self.Promise = promise
        
    def run(self):
        try:    
            out = self.Processor._process(self.Item)
        except:
            self.Promise.exception(sys.exc_info())
        else:
            self.Promise.complete(out)
        finally:    
            self.Processor = None
            self.Promise = None
            self.Item = None

class Processor(Primitive):
    
    def __init__(self, max_workers = None, queue_capacity = None, output = None, stagger=None, delegate=None,
            put_timeout=None):
        Primitive.__init__(self)
        #assert output is None or isinstance(output, Processor)
        self.Output = output
        self.WorkerQueue = TaskQueue(max_workers, capacity=queue_capacity, stagger=stagger)
        self.PutTimeout = put_timeout
        self.Delegate = delegate
        
    def hold(self):
        self.WorkerQueue.hold()

    def release(self):
        self.WorkerQueue.release()
        
    def put(self, item, timeout=-1):
        if timeout == -1: timeout = self.PutTimeout
        promise = Promise(item)
        self.WorkerQueue.addTask(_WorkerTask(self, item, promise), timeout)
        return promise
        
    def join(self):
        return self.WorkerQueue.join()
        
    def _process(self, item):
        #print("%x: Processor._process: item: %s" % (id(self), item))
        try:    out = self.process(item)
        except:
            exc_type, exc_value, tb = sys.exc_info()
            if self.Delegate is not None:
                self.Delegate.itemFailed(item, exc_type, exc_value, tb)
            raise
        #print("%x: out: %s" % (id(self), out))
        if self.Delegate is not None:
            self.Delegate.itemProcessed(item, out)
        if out is not None and self.Output is not None:
            self.Output.put(out)
        return out
            
    def process(self, items):
        # override me
        pass
