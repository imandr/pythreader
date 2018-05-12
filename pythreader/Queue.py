from .core import Primitive, synchronized

class Queue(Primitive):

    def __init__(self, capacity=None):
        Primitive.__init__(self)
        self.Capacity = capacity
        self.List = []
        self.Closed = False
    
    @synchronized
    def close(self):
        self.Closed = True
        self.wakeup()
        
    @synchronized    
    def append(self, item):
        assert not self.Closed, "The queue is closed"
        while self.Capacity is not None and len(self.List) >= self.Capacity:
            self.await()
        self.List.append(item)
        self.wakeup()
        
    def __lshift__(self, item):
        return self.add(item)
    
    @synchronized    
    def insert(self, item):
        assert not self.Closed, "The queue is closed"
        while self.Capacity is not None and len(self.List) >= self.Capacity:
            self.await()
        self.List.insert(0, item)
        self.wakeup()

    def __rrshift__(self, item):
        return self.push(item)
        
    @synchronized
    def pop(self):
        while len(self.List) == 0 and not self.Closed:
            self.await()
        if len(self.List) == 0:
            return None     # closed
        item = self.List[0]
        self.List = self.List[1:]
        self.wakeup()
        return item
        
    @synchronized
    def flush(self):
        self.List = []
        self.wakeup()
        
    @synchronized
    def items(self):
        return self.List
        
    @synchronized
    def look(self):
        return self.List[0] if self.List else None
        
    @synchronized
    def popIfFirst(self, x):
        if self.List:
            first = self.List[0]
            if first is x or first == x:
                self.pop()
                return x
        return None
        
    @synchronized
    def __len__(self):
        return len(self.List)
        
