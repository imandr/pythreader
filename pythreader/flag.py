from .core import Primitive

class Flag(Primitive):
    
    def __init__(self, value=False):
        Primitive.__init__(self)
        self._Value = value
        
    def set(self, value=True):
        self._Value = value
        self.wakeup()
        
    def get(self):
        return self._Value
        
    value = property(get, set)
        
    def sleep(self, until=None, timeout = None):
        if until is None:
            until = lambda x: x
        done = False
        while not done:
            with self:
                v = self._Value
                done = until(v)
            if not done:
                Primitive.sleep(self, timeout)
                
            