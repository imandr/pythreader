VERSION = 1.0

BUILD_DIR = $(HOME)/build/threads
TAR_DIR = /tmp/$(USER)
TAR_FILE = $(TAR_DIR)/threads_$(VERSION).tar

all: tarball

tarball: clean build $(TAR_DIR)
	cd $(BUILD_DIR)/..; tar cf $(TAR_FILE) threads
	@echo 
	@echo Tar file $(TAR_FILE) is ready
	@echo


clean:
	rm -rf $(BUILD_DIR) $(TAR_FILE)
    
build: $(BUILD_DIR)
	cd src; make VERSION=$(VERSION) BUILD_DIR=$(BUILD_DIR) build
    
$(BUILD_DIR):
	mkdir -p $@
    
$(TAR_DIR):
	mkdir -p $@

