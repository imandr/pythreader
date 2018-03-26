from threading import RLock, Thread, Event, Condition, Semaphore

Waiting = []
In = []

def synchronized(method):
    def smethod(self, *params, **args):
        #print "@synchronized: wait %s..." % (method,)
        q = "%s(%x).@synch(%s)" % (self, id(self), method)
        Waiting.append(q)
        with self:
            Waiting.remove(q)
            #print "@synchronized: in %s" % (method,)
            In.append(q)
            out = method(self, *params, **args)
        #print "@synchronized: out %s" % (method,)
        In.remove(q)
        return out
    return smethod

def gated(method):
    def smethod(self, *params, **args):
        #print "@synchronized: wait %s..." % (method,)
        q = "%s(%x).@gated(%s)" % (self, id(self), method)
        Waiting.append(q)
        with self._Gate:
            Waiting.remove(q)
            #print "@synchronized: in %s" % (method,)
            In.append(q)
            out = method(self, *params, **args)
        #print "@synchronized: out %s" % (method,)
        In.remove(q)
        return out
    return smethod


def printWaiting():
    print "waiting:----"
    for w in Waiting:
        print w
    print "in:---------"
    for w in In:
        print w

class Primitive:
    def __init__(self, gate=1, lock=None):
        self._Lock = lock if lock is not None else RLock()
        self._WakeUp = Condition(self._Lock)
        self._Gate = Semaphore(gate)

    def __enter__(self):
        return self._Lock.__enter__()
        
    def __exit__(self, exc_type, exc_value, traceback):
        return self._Lock.__exit__(exc_type, exc_value, traceback)

    @synchronized
    def await(self, timeout = None, function=None, arguments=()):
        self._WakeUp.wait(timeout)
        if function is not None:
            return function(*arguments)

    @synchronized
    def wakeup(self, n=1, all=False, function=None, arguments=()):
        if function is not None:
            function(*arguments)
        if all:
            self._WakeUp.notifyAll()
        else:
            self._WakeUp.notify(n)

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

