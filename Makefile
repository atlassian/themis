dir = $(shell pwd)

build:
	pip install -r requirements.txt
	cd $(dir)/web/ && npm install

test:
	PYTHONPATH=$(dir)/test nosetests --with-coverage --cover-package=themis test/

server:
	PYTHONPATH=$(dir)/src src/themis/scaling.py server_and_loop -p 9090

.PHONY: build test
