#
# Tracer for single thread applicatuons
#

import time

class Context:

    def __init__(self, tracer, path):
        self.Tracer = tracer
        self.Path = path
        self.N = 0
        self.T = 0.0
        self.T0 = time.time()
    
    def __enter__(self):
        self.T0 = time.time()
        
    def __exit__(self, *params):
        self.T += time.time() - self.T0
        self.N += 1
        self.Tracer.popContext(self)
        
class Tracer(object):
    
    def __init__(self, adjust=True):
        self.Contexts = {}    # path->context
        self.ContextStack = []
        self.Delay = 0.0
        if adjust:
            self.Delay = Tracer.calc_delay()
        
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
        c = self.Contexts.get(path)
        if c is None:
            c = Context(self, path)
            self.Contexts[path] = c
        self.ContextStack.append(c)
        return c
    
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
        
    def rollup(self):
        contexts = sorted(self.Contexts.items())  # sort by path
        stats = [[p, c.N, c.T] for p, c in contexts]
        n = len(stats)
        for i, tup in enumerate(stats):
            t = tup[2]
            p_slash = tup[0] + '/'
            for j in xrange(i+1,n):
                pp, nn, tt = stats[j]
                if pp.startswith(p_slash):
                    t += tt
            tup[2] = t
        return stats

    def printStats(self):
        for p, t, n, tn in self.stats():
            print "%-40s %6d %.6f %.6f" % (p, n, t, tn)
            
    def stats(self, adjusted = True):
        contexts = sorted(self.Contexts.items())
        if adjusted and self.Delay > 0.0:
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
                
if __name__ == '__main__':
    t=Tracer()

    with t["top"]:
        #time.sleep(0.01)
        with t["middle"]:
            for i in range(3):
                #time.sleep(0.01)
                with t["bottom"]:
                    for j in range(5):
                        #time.sleep(0.01)
                        with t["/new_top"]:
                            for k in range(7):
                                with t["under_new_top"]:
                                    for l in range(11):
                                        time.sleep(0.01)
                                        pass
                with t["bottom2"]:
                    for j in range(6):
                        #time.sleep(0.01)
                        for k in range(8):
                            with t["/new_top"]:
                                pass
                


    t.printStats()
            