from .core import Primitive, synchronized, Timeout
from threading import get_ident, RLock

class DebugLock(object):
    
    def __init__(self):
        self.R = RLock()
        
    def acquire(self, *params, **args):
        print(self, "acquire by ", get_ident(), "...")
        self.R.acquire(*params, **args)
        print(self, "acquired by ", get_ident())
        
    def release(self):
        print(self, "released by ", get_ident())
        self.R.release()
        
    def __enter__(self):
        return self.acquire()
        
    def __exit__(self, *params):
        return self.release()
    

class Promise(Primitive):
    
    def __init__(self, data=None, callbacks = [], name=None):
        """
        Creates new Promise object.
        
        Args:
            data: Arbitrary user-defined data to be associated with the promise. Can be anything. pythreader does not use it.
            callbacks (list): List of Promise callbacks objects. Each object may have ``oncomplete`` and/or ``onexception`` methods defined. See Notes below.
            name (string): Name for the new Promise object, optional.
        
        Notes:
            
        """
        Primitive.__init__(self, name=name)    #, lock=DebugLock())
        self.Data = data
        self.Callbacks = callbacks[:]
        self.Complete = False
        self.Cancelled = False
        self.Result = None
        self.ExceptionInfo = None     # or tuple (exc_type, exc_value, exc_traceback)
        self.RaiseException = True
        self.OnComplete = self.OnException = self.OnCancel = None
        self.Chained = []

    @synchronized
    def then(self, oncomplete=None, onexception=None):
        """
        Creates new Promise object, which will be chained to the ``self`` promise with provided ``oncomplete`` and ``onexception`` callbacks.
        
        Args:
            data: Arbitrary user-defined data to be associated with the promise. Can be anything. pythreader does not use it.
            callbacks (list): List of Promise callbacks objects. Each object may have ``oncomplete`` and/or ``onexception`` methods defined. See Notes below.
            name (string): Name for the new Promise object, optional.
        """
        p = Promise()
        if oncomplete is not None:
            p.oncomplete(oncomplete)
        if onexception is not None:
            p.onexception(onexception)
        self.chain(p)
        return p

    @synchronized
    def oncomplete(self, cb):
        if self.Complete:
            cb(self, self.Result)
        self.OnComplete = cb
        return self
        
    @synchronized
    def onexception(self, cb):
        if self.ExceptionInfo:
            cb(self, *self.ExceptionInfo)
        self.OnException = cb
        return self
        
    @synchronized
    def oncancel(self, cb):
        if self.Cancelled:
            cb(self)
        self.OnCancel = cb
        return self
        
    @synchronized
    def addCallback(self, cb):
        if not self.Cancelled:
            if self.Cancelled and hasattr(cb, "oncancel"):
                cb.oncancel(self)
            elif self.Complete and hasattr(cb, "oncomplete"):
                cb.oncomplete(self, self.Result)
            elif self.ExceptionInfo and hasattr(cb, "onexception"):
                cb.onexception(self, *self.ExceptionInfo)
            self.Callbacks.append(cb)
        return self

    @synchronized
    def chain(self, *promises, cancel_chained = True):
        if self.ExceptionInfo:
            exc_type, exc_value, exc_traceback = self.ExceptionInfo
            for p in promises:
                p.exception(exc_type, exc_value, exc_traceback)
        elif self.Complete:
            for p in promises:
                p.complete(self.Result)
        elif self.Cancelled and cancel_chained:
            for p in promises:
                p.cancel()
        else:
            self.Chained += list(promises)
        return self

    @synchronized
    def complete(self, result=None):
        self.Result = result
        self.Complete = True
        if not self.Cancelled:
            stop = False
            if self.OnComplete is not None:
                stop = not not self.OnComplete(self, self.Result)
            for cb in self.Callbacks:
                if stop:
                    break
                if hasattr(cb, "oncomplete"):
                    stop = not not cb.oncomplete(self.Result, self)
        for p in self.Chained:
            p.complete(result)
        self.wakeup()
        self._cleanup()

    @synchronized
    def exception(self, exc_type, exc_value, exc_traceback):
        self.ExceptionInfo = (exc_type, exc_value, exc_traceback)
        if not self.Cancelled:
            stop = False
            if self.OnException is not None:
                stop = bool(self.OnException(self, exc_type, exc_value, exc_traceback))
            for cb in self.Callbacks:
                if stop:
                    break
                if hasattr(cb, "onexception"):
                    stop = not not cb.onexception(self, exc_type, exc_value, exc_traceback)
            self.RaiseException = not stop
        for p in self.Chained:
            #print("forwarding exception to the chained promise...")
            p.exception(exc_type, exc_value, exc_traceback)
        self.wakeup()
        self._cleanup()

    @synchronized
    def cancel(self, cancel_chained = True):
        if not self.Cancelled:
            stop = False
            if self.OnCancel is not None:
                #print("calling OnException...")
                stop = not not self.OnCancel(self)
            for cb in self.Callbacks:
                if stop:
                    break
                if hasattr(cb, "oncancel"):
                    stop = not not cb.oncancel(self)
            if cancel_chained:
                for p in self.Chained:
                    p.cancel()
        self.Cancelled = True
        self.wakeup()
        self._cleanup()

    @synchronized
    def wait(self, timeout=None):
        #print("thread %s: wait(%s)..." % (get_ident(), self))
        pred = lambda x: x.Complete or x.Cancelled or self.ExceptionInfo is not None
        self.sleep_until(pred, self, timeout=timeout)
        try:
            if self.Complete:
                return self.Result
            elif self.Cancelled:
                return None
            elif self.ExceptionInfo:
                if self.RaiseException:
                    _, e, _ = self.ExceptionInfo
                    raise e 
            else:
                raise Timeout()
        finally:
            self._cleanup()

    def _cleanup(self):
        self.Chained = []
        self.Callbacks = []
        self.OnException = self.OnComplete = None

    @staticmethod
    def all(*args):
        if args and isinstance(args[0], (tuple, list)):
            promises = args[0]
        else:
            promises = args
        return ANDPromise(promises)

    @staticmethod
    def any(*args):
        if args and isinstance(args[0], (tuple, list)):
            promises = args[0]
        else:
            promises = args
        return ORPromise(promises)
    
class ORPromise(Primitive):
    
    def __init__(self, promises):
        Primitive.__init__(self)
        self.Fulfilled = None
        for p in promises:
            p.addCallback(self)

    @synchronized
    def oncomplete(self, promise, result):
        if self.Fulfilled is None:
            self.Fulfilled = promise
            self.wakeup()

    @synchronized
    def wait(self, timeout = None):
        while self.Fulfilled is None:
            self.sleep(timeout)
        return self.Fulfilled.Result

class ANDPromise(Primitive):
    
    def __init__(self, promises):
        Primitive.__init__(self)
        self.Promises = promises
        
    def wait(self, timeout=None):
        return [p.wait(timeout) for p in self.Promises]
