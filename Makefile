dir = $(shell pwd)

build:
	pip install -r requirements.txt
	make npm

build-local:
	pip install --user -r requirements.txt
	make npm

install-prereq:
	which apt-get && sudo apt-get -y install libblas-dev liblapack-dev
	which yum && sudo yum -y install blas-devel lapack-devel numpy-f2py

npm:
	cd $(dir)/web/ && npm install

test:
	PYTHONPATH=$(dir)/test nosetests --with-coverage --with-xunit --cover-package=themis test/

lint:
	pylint --rcfile=.pylintrc src/

server:
	eval `ssh-agent -s` && PYTHONPATH=$(dir)/src src/themis/main.py server_and_loop --port=8081 --log=themis.log

.PHONY: build test
