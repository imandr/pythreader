from .core import Primitive, synchronized
from .dequeue import DEQueue
from .TaskQueue import Task, TaskQueue

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
    
    def __init__(self, max_workers = None, queue_capacity = None, output = None, stagger=None, delegate=None):
        Primitive.__init__(self)
        assert output is None or isinstance(output, Processor)
        self.Output = output
        self.WorkerQueue = TaskQueue(max_workers, capacity=queue_capacity, stagger=stagger, delegate=delegate)
        
    def hold(self):
        self.WorkerQueue.hold()

    def release(self):
        self.WorkerQueue.release()
        
    def add(self, item):
        self.WorkerQueue << WorkerTask(self, item)
        
    def join(self):
        return self.WorkerQueue.join()
        
    def _process(self, item):
        #print("%x: Processor._process: item: %s" % (id(self), item))
        out = self.process(item)
        #print("%x: out: %s" % (id(self), out))
        if out is not None and self.Output is not None:
            #print("forwarding")
            self.Output.add(out)
        
    def process(self, items):
        # override me
        pass
