from .core import PyThread
import time

class Timer(PyThread):
    
    def __init__(self, t, fcn, *params, interval=None, start=True, name=None, daemon=True, onexception=None, **args):
        PyThread.__init__(self, name=name, daemon=daemon)
        self.T = t if t > 3e8 else time.time() + t
        self.Fcn = fcn
        self.OnException = onexception
        self.Params = params
        self.Args = args
        self.Interval = interval
        self.Cancelled = False
        self.Paused = False
        if start:
            self.start()

    def run(self):
        try:
            again = True
            while again and not self.Cancelled:
                again = False
                now = time.time()
                if now < self.T:
                    self.sleep(self.T - now)
                while self.Paused and not self.Cancelled:
                    self.sleep(100)
                if not self.Cancelled:
                    try:    self.Fcn(*self.Params, **self.Args)
                    except:
                        if self.OnException is not None:
                            try:
                                self.OnException(*sys.exc_info())
                            except:
                                pass
                    if not self.Cancelled and self.Interval:
                        self.T = time.time() + self.Interval
                        again = True
        finally:
            # to break any circular links
            self.Fcn = self.Args = self.Params = None

    def cancel(self):
        self.Cancelled = True
        self.wakeup()

    def pause(self):
        self.Paused = True
        self.wakeup()

    def resume(self):
        self.Paused = False
        self.wakeup()
