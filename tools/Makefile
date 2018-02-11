FILES = \
    spawner.py
DST_DIR = $(BUILD_DIR)/bin

build: $(DST_DIR)
	cp $(FILES) $(DST_DIR)
	cd $(DST_DIR); chmod ugo+x $(FILES)
    
$(DST_DIR):
	mkdir -p $@

    
