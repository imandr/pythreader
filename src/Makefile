FILES = \
    core.py  __init__.py  Queue.py  Subprocess.py  TaskQueue.py
LIB_DIR = $(BUILD_DIR)/threads

build: $(LIB_DIR)
	cp $(FILES) $(LIB_DIR)
	echo Version="$(VERSION)" > $(LIB_DIR)/Version.py
    
$(LIB_DIR):
	mkdir -p $@

    
