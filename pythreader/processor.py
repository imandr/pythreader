from .core import Primitive, synchronized
from .dequeue import DEQueue
from .TaskQueue import Task, TaskQueue
import sys, traceback

class WorkerTask(Task):
    
    def __init__(self, processor, item):
        Task.__init__(self)
        self.Processor = processor
        self.Item = item
        
    def run(self):
        try:    
            self.Processor._process(self.Item)
        finally:    
            self.Processor = None

class Processor(Primitive):
    
    def __init__(self, max_workers = None, queue_capacity = None, output = None, stagger=None, delegate=None,
            add_timeout=None):
        Primitive.__init__(self)
        #assert output is None or isinstance(output, Processor)
        self.Output = output
        self.WorkerQueue = TaskQueue(max_workers, capacity=queue_capacity, stagger=stagger)
        self.AddTimeout = add_timeout
        self.Delegate = delegate
        
    def hold(self):
        self.WorkerQueue.hold()

    def release(self):
        self.WorkerQueue.release()
        
    def add(self, item, timeout=-1):
        if timeout == -1: timeout = self.AddTimeout
        self.WorkerQueue.addTask(WorkerTask(self, item), timeout)
        
    def join(self):
        return self.WorkerQueue.join()
        
    def _process(self, item):
        #print("%x: Processor._process: item: %s" % (id(self), item))
        try:    out = self.process(item)
        except:
            exc_type, exc_value, tb = sys.exc_info()
            if self.Delegate is not None:
                self.Delegate.itemFailed(item, exc_type, exc_value, tb)
        else:
            #print("%x: out: %s" % (id(self), out))
            if out is not None:
                if self.Delegate is not None:
                    self.Delegate.itemProcessed(item, out)
                if self.Output is not None:
                    #print("forwarding")
                    self.Output.add(out)
            else:
                if self.Delegate is not None:
                    self.Delegate.itemDiscarded(item)
            
        
    def process(self, items):
        # override me
        pass
