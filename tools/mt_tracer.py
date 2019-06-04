#
# Thread safe version
#
# Usage:
#
# 1. Create record keeper object in the main thread:
#
#    keeper = TraceRecordKeeper()
#
# 2. Pass the keeper reference to each thread and have them create their own tracers:
#
#    class MyThread(Thread):
#       def __init__(self, ..., trace_keeper, ...):
#           ...
#           self.Trace = trace_keeper.tracer()
#
# 3. Use their own trace objects within threads:
#
#       def run(self):
#           ...
#           with self.Trace["fragment"]:
#               ...
#
# 4. Get or print stats from the keeper. This can be done at any time from any thread
#
#   keeper.printStats()
#

import time
from pythreader import Primitive, synchronized
        
class ContextProxy:
    
    def __init__(self, tracer, context):
        self.Context = context
        self.Tracer = tracer
        
    def __enter__(self):
        self.T0 = time.time()
        
    def __exit__(self, *params):
        t = time.time() - self.T0
        self.Context.addSegment(t)
        self.Tracer.popContext(self.Context)
    
class Context(Primitive):

    def __init__(self, path):
        Primitive.__init__(self)
        self.Path = path
        self.N = 0
        self.T = 0.0

    @synchronized
    def addSegment(self, t):
        self.T += t
        self.N += 1

class TraceRecordKeeper(Primitive):

    def __init__(self, adjust = False):
        Primitive.__init__(self)
        self.Contexts = {}
        self.Delay = 0.0
        self.Adjust = adjust
        if adjust:
            self.Delay = Tracer.benchmark()
        
    @synchronized
    def context(self, path):
        c = self.Contexts.get(path)
        if c is None:
            c = Context(path)
            self.Contexts[path] = c
        return c

    @synchronized
    def printStats(self):
        for p, t, n, tn in self.stats():
            print "%-40s %6d %11.6f %11.6f" % (p, n, t, tn)
            
    @synchronized
    def stats(self):
        contexts = sorted(self.Contexts.items())
        if self.Delay > 0.0:
            stats = []
            for i, (p, c) in enumerate(contexts):
                t = c.T
                p_slash = p + '/'
                for pp, cc in contexts[i+1:]:
                    if pp.startswith(p_slash):
                        t = max(0.0, t - self.Delay * cc.N)
                    else:
                        break
                stats.append((p, t, c.N, t/c.N))
        else:
            stats = [(p, c.T, c.N, c.T/c.N) for p, c in contexts]
        return stats
    
    def tracer(self):
        return Tracer(self)
        
class Tracer(object):
    
    def __init__(self, record_keeper):
        self.Keeper = record_keeper
        self.ContextStack = []
        
    @staticmethod
    def calc_delay():
        t = Tracer(adjust=False)
        for _ in range(1000):
            with t["top"]:
                with t["bottom"]:
                    pass
        ttop = t.Contexts["/top"].T
        tbottom = t.Contexts["/top/bottom"].T
        return max(0.0, ttop - tbottom)/1000

    def pushContext(self, path):
        if path[0] != '/':
            if self.ContextStack:
                path = self.ContextStack[-1].Path + '/' + path
            else:
                path = '/' + path
        c = self.Keeper.context(path)
        self.ContextStack.append(c)
        return ContextProxy(self, c)
    
    __getitem__ = pushContext
    __call__ = pushContext
    
    def popContext(self, c):
        cc = self.ContextStack.pop()
        assert c is cc
    
    def begin(self, path):
        c = self.pushContext(path)
        c.__enter__()
        
    def end(self):
        c = self.ContextStack[-1]
        c.__exit__()
        
                
if __name__ == '__main__':
    import random, time
    from threading import Thread

    class MyThread(Thread):
    
        def __init__(self, keeper):
            Thread.__init__(self)
            self.T = keeper.tracer()
    
        def long(self):
            with self.T["long"]:
                time.sleep(1.0)
                for _ in range(13):
                    with self.T["/inner"]:
                        time.sleep(0.01)
        
        def short(self):
            with self.T["short"]:
                time.sleep(0.1)
                for _ in range(5):
                    with self.T["/inner"]:
                        with self.T["bottom"]:
                            time.sleep(0.01)
   
        def run(self):
            for _ in range(7):
                with self.T["run"]:
                    if random.random() < 0.5:
                        self.short()
                    else:
                        self.long()
    T = TraceRecordKeeper()
    threads = [MyThread(T) for _ in range(50)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    T.printStats()