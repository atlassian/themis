dir = $(shell pwd)

build:
	pip install -r requirements.txt
	cd $(dir)/web/ && npm install

test:
	PYTHONPATH=$(dir)/test nosetests --with-coverage --cover-package=themis test/

lint:
	pylint --rcfile=.pylintrc src/

server:
	eval `ssh-agent -s` && PYTHONPATH=$(dir)/src src/themis/main.py server_and_loop -p 8081

.PHONY: build test
