from .core import Primitive, synchronized, Timeout

class Promise(Primitive):
    
    def __init__(self, data=None, callbacks = []):
        Primitive.__init__(self)
        self.Data = data
        self.Callbacks = callbacks[:]
        self.Complete = False
        self.Canceled = False
        self.Result = None
        self.ExceptionInfo = None     # or tuple (exc_type, exc_value, exc_traceback)
        self.OnDone = self.OnCancel = self.OnException = None

    @synchronized
    def ondone(self, cb):
        self.OnDone = cb
        
    @synchronized
    def oncancel(self, cb):
        self.OnCancel = cb
        
    @synchronized
    def oncexception(self, cb):
        self.OnException = cb
        
    @synchronized
    def addCallback(self, cb):
        if self.Complete and not self.Canceled:
            cb(self)
        self.Callbacks.append(cb)        
        
    @synchronized
    def exception(self, exc_type, exc_value, exc_traceback):
        self.ExceptionInfo = (exc_type, exc_value, exc_traceback)
        if self.OnException is not None:
            self.OnExceptipn(self)
        self.wakeup()
        self._cleanup()
        
    @synchronized
    def complete(self, result=None):
        self.Result = result
        self.Complete = True
        if not self.Canceled:
            if self.OnDone is not None:
                self.OnDone(self.Result,)
            for cb in self.Callbacks:
                if cb(self) == "stop":
                    break
        self.Callbacks = []
        self.wakeup()
        self._cleanup()
    
    def is_complete(self):
        return self.Complete
        
    @synchronized
    def cancel(self):
        self.Canceled = True
        if self.OnCancel is not None:
            self.OnCancel(self)
        self.wakeup()
        self._cleanup()
        
    @synchronized
    def wait(self, timeout=None):
        t1 = None if timeout is None else time.time() + timeout
        while not self.Complete and not self.Canceled and self.ExceptionInfo is None and (t1 is None or time.time() < t1):
            dt = None if t1 is None else max(0.0, t1 - time.time())
            self.sleep(dt)
        try:
            if self.Complete:
                return self.Result
            elif self.Canceled:
                return None
            elif self.ExceptionInfo:
                _, e, _ = self.ExceptionInfo
                raise e 
            else:
                raise Timeout()
        finally:
            self._cleanup()
            
            
    @synchronized
    def _cleanup(self):
        self.Callbacks = []
        self.OnCancel = self.OnException = self.OnDone = None
    
class ORPromise(Primitive):
    
    def __init__(self, promises):
        Primitive.__init__(self)
        self.Fulfilled = None
        for p in promises:
            p.addCallback(self, promise_callback)

    @synchronized
    def promise_callback(self, promise):
        self.Fulfilled = promise
        self.wakeup()
    
    @synchronized
    def wait(self, timeout = None):
        while self.Fulfilled is None:
            self.sleep(timeout)
        return sef.Fulfilled

class ANDPromise(Primitive):
    
    def __init__(self, promises):
        Primitive.__init__(self)
        self.Promises = promises
        
    def wait(self, timeout=None):
        return [p.wait(timeout) for p in self.Promises]
