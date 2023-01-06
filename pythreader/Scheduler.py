from .core import PyThread, synchronized
from .task_queue import Task, TaskQueue
import time, uuid, traceback, random
import sys

class Job(object):
    
    def __init__(self, id, t, interval, jitter, fcn, params, args):
        self.F = fcn
        self.Params = params or ()
        self.Args = args or {}
        self.ID = id
        self.Interval = interval
        self.Jitter = jitter or 0.0
        self.NextT = t
        
    def __str__(self):
        return f"Job({self.ID})"
        
    __repr__ = __str__
        
    def run(self):
        start = time.time()
        exc_info = None
        try:    next_t = self.F(*self.Params, **self.Args)
        except:
            exc_info = sys.exc_info()
            next_t = None
        if next_t is None:
            if self.Interval is not None:
                next_t = start + self.Interval + random.random() * self.Jitter
        elif next_t == "stop":
            next_t = None
        elif next_t < 3.0e7:
            # if next_t is < 1980, it's relative time
            next_t += start + random.random() * self.Jitter
        return next_t, exc_info

class JobThread(PyThread):
    
    def __init__(self, scheduler, job):
        PyThread.__init__(self, name=f"Scheduler({scheduler})/job{job.ID}", daemon=True)
        self.Scheduler = scheduler
        self.Job = job
        
    def run(self):
        scheduler = self.Scheduler
        job = self.Job
        self.Job = self.Scheduler = None
        next_t, exc_info = job.run()
        if exc_info:
            scheduler.job_failed(job, next_t, *exc_info)
        else:
            scheduler.job_ended(job, next_t)

class Scheduler(PyThread):
    def __init__(self, max_concurrent = 10, stop_when_empty = False, delegate=None, daemon=False, name=None, **args):
        PyThread.__init__(self, daemon=daemon, name=name)
        self.Timeline = []      # [job, ...]
        self.Delegate = delegate
        self.StopWhenEmpty = stop_when_empty
        self.Stop = False

    # delegate interface used to wait until the task queue is empty
    def job_ended(self, job, next_t):
        if self.Delegate is not None and hasattr(self.Delegate, "jobEnded"):
            try:    self.Delegate.jobEnded(self, task.JobID)
            except: pass
        if next_t is not None:
            self.add_job(job, next_t)
        self.wakeup()

    def job_failed(self, job, next_t, exc_type, exc_value, tb):
        if self.Delegate is not None and hasattr(self.Delegate, "jobFailed"):
            try:    self.Delegate.jobFailed(self, job.ID, exc_type, exc_value, tb)
            except: pass
        if next_t is not None:
            self.add_job(job, next_t)
        self.wakeup()

    def stop(self):
        self.Stop = True
        self.wakeup()
        
    @synchronized
    def add_job(self, job, t):
        job.NextT = t
        self.Timeline.append(job)
        self.wakeup()
        
    @synchronized        
    def add(self, fcn, *params, interval=None, t0=None, id=None, jitter=0.0, param=None, **args):
        #
        # t0 - first time to run the task. Default:
        #   now + interval or now if interval is None
        # interval - interval to repeat the task. Default: do not repeat
        #
        # fcn:
        #   next_t = fcn()
        #   next_t = fcn(param)
        #   next_t = fcn(**args)
        # 
        #   next_t:
        #       "stop" - remove task
        #       int or float - next time to run
        #       None - run at now+interval next time
        #
        if param is not None:       # for backward compatibility
            params = (param,)
        if id is None:
            id = uuid.uuid4().hex
        if t0 is None:
            t0 = time.time() + (interval or 0.0) + random.random()*jitter
        elif t0 < 10*365*24*3600:           # ~ Jan 1 1980
            t0 = time.time() + t0
        job = Job(id, t0, interval, jitter, fcn, params, args)
        self.add_job(job, t0)
        return id
        
    @synchronized
    def remove(self, job_id):
        self.Timeline = [j for j in self.Timeline if j.ID != job_id]

    @synchronized
    def run_jobs(self):
        keep_jobs = []
        next_run = None
        for job in self.Timeline:
            if job.NextT <= time.time():
                t = JobThread(self, job)
                t.start()
                self.wakeup()
            else:
                next_run = min(next_run or job.NextT, job.NextT)
                keep_jobs.append(job)
        self.Timeline = keep_jobs
        return next_run

    @synchronized
    def is_empty(self):
        return not self.Timeline

    def run(self):
        while not self.Stop and not (self.is_empty() and self.StopWhenEmpty):
            delta = 100
            if self.Timeline:
                next_t = self.run_jobs()
                if next_t is not None:
                    delta = next_t - time.time()
            if delta > 0:
                self.sleep(delta)

    @synchronized        
    def wait_until_empty(self):
        while not self.is_empty():
            self.sleep(10)
    
    join = wait_until_empty

if __name__ == "__main__":
    from datetime import datetime
    
    s = Scheduler()
    
    class NTimes(object):

        def __init__(self, n):
            self.LastRun = None
            self.N = n

        def __call__(self, message):
            t = datetime.now()
            delta = None if self.LastRun is None else t - self.LastRun
            print("%s: %s delta:%s" % (t.strftime("%H:%M:%S.%f"), message, delta))
            self.LastRun = t
            self.N -= 1
            time.sleep(0.2)
            if self.N <= 0:
                print("stopping", message)
                return "stop"

    #time.sleep(1.0)
    s.add(NTimes(10), "green 1.5 sec", interval=1.5)
    s.add(NTimes(7), "blue 0.5 sec", interval=0.5)
    s.start()

    print("waiting for the scheduler to finish...")
    #s.join()
    s.wait_until_empty()
    s.stop()
    s.join()
    print("stopped")
