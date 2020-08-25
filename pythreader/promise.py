from .core import Primitive, synchronized, Timeout

class Promise(Primitive):
    
    def __init__(self, data=None, callbacks = []):
        Primitive.__init__(self)
        self.Data = data
        self.Callbacks = callbacks[:]
        self.Complete = False
        self.Canceled = False
        self.Result = None

    @synchronized
    def addCallback(self, cb):
        if self.Complete and not self.Canceled:
            cb(self)
        self.Callbacks.append(cb)            
        
    @synchronized
    def complete(self, result=None):
        self.Result = result
        self.Complete = True
        if not self.Canceled:
            for cb in self.Callbacks:
                if cb(self) == "stop":
                    break
        self.Callbacks = []
        self.wakeup()
    
    def is_complete(self):
        return self.Complete
        
    @synchronized
    def cancel(self):
        self.Canceled = True
        self.Callbacks = []
        self.wakeup()
        
    @synchronized
    def wait(self, timeout=None):
        t1 = None if timeout is None else time.time() + timeout
        while not self.Complete and not self.Canceled and (t1 is None or time.time() < t1):
            dt = None if t1 is None else max(0.0, t1 - time.time())
            self.sleep(dt)
        if self.Complete:
            return self.Result
        elif self.Canceled:
            return None
        else:
            raise Timeout()