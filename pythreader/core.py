from threading import RLock, Thread, Event, Condition, Semaphore, currentThread
import time
import sys

Waiting = []
In = []

def threadName():
    t = currentThread()
    return str(t)

def synchronized(method):
    def smethod(self, *params, **args):
        with self:
            out = method(self, *params, **args)
        return out
    return smethod

def gated(method):
    def smethod(self, *params, **args):
        with self._Gate:
            out = method(self, *params, **args)
        return out
    return smethod


def printWaiting():
    print("waiting:----")
    for w in Waiting:
        print(w)
    print("in:---------")
    for w in In:
        print(w)

class Primitive:
    def __init__(self, gate=1, lock=None):
        self._Lock = lock if lock is not None else RLock()
        self._WakeUp = Condition(self._Lock)
        self._Gate = Semaphore(gate)
        self._Kind = self.__class__.__name__
        
    def __str__(self):
        return "[%s@%x]" % (self.kind, id(self))

    def __get_kind(self):
        return self._Kind

    def __set_kind(self, kind):
        self._Kind = kind

    kind = property(__get_kind, __set_kind)

    def getLock(self):
        return self._Lock
        
    def __enter__(self):
        #t = currentThread()
        #print ">>>entry by thread %s %x: %s %x..." % (t.__class__.__name__, id(t), self.kind, id(self))
        return self._Lock.__enter__()
        
    def __exit__(self, exc_type, exc_value, traceback):
        #t = currentThread()
        #print "<<<<exit by thread %s %x: %s %x" % (t.__class__.__name__, id(t), self.kind, id(self))
        return self._Lock.__exit__(exc_type, exc_value, traceback)

    @synchronized
    def sleep(self, timeout = None, function=None, arguments=()):
        self._WakeUp.wait(timeout)
        if function is not None:
            return function(*arguments)

    # await is a reserved word in Python 3, use "wakeup" instead
    @synchronized
    def wakeup(self, n=1, all=False, function=None, arguments=()):
        if function is not None:
            function(*arguments)
        if all:
            self._WakeUp.notifyAll()
        else:
            self._WakeUp.notify(n)

if sys.version_info < (3,0):
    # await is a reserved word in Python 3, keep it for backward compatibility
    # in Python 2.
    setattr(Primitive, "await", Primitive.sleep)


class PyThread(Thread, Primitive):
    def __init__(self, func=None, *params, **args):
        Thread.__init__(self)
        Primitive.__init__(self)
        self.Func = func
        self.Params = params
        self.Args = args
        
    def run(self):
        if self.Func is not None:
            self.Func(*self.Params, **self.Args)

class TimerThread(PyThread):
    def __init__(self, function, interval, *params, **args):
        PyThread.__init__(self)
        self.Interval = interval
        self.Func = function
        self.Params = params
        self.Args = args
        self.Pause = False

    def run(self):
        while True:
            if self.Pause:
                self.sleep()
            self.Func(*self.Params, **self.Args)
            time.sleep(self.Interval)
    
    def pause(self):
        self.Pause = True
        
    def resume(self):
        self.Pause = False
        self.wakeup()
                
            
            
