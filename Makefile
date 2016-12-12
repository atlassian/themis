dir = $(shell pwd)
VENV_DIR = .venv
IMAGE_NAME = atlassianlabs/themis
# VENV_RUN = . $(VENV_DIR)/bin/activate
# TODO: there is a bug in some virtualenv environments, we need to manually include this path here
VENV_RUN = . $(VENV_DIR)/bin/activate && export PYTHONPATH=.venv/lib64/python2.7/dist-packages

usage:             ## Show this help
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

build:             ## Install local pip and npm dependencies
	(test `which virtualenv` || pip install virtualenv || sudo pip install virtualenv)
	(test -e $(VENV_DIR) || (virtualenv $(VENV_DIR) && $(VENV_RUN) && pip install --upgrade pip))
	# due to a bug in scipy, numpy needs to be installed first:
	($(VENV_RUN) && pip install numpy)
	($(VENV_RUN) && pip install -r requirements.txt)
	make npm

install-prereq:    ## Install prerequisites via apt-get or yum (if available)
	which apt-get && sudo apt-get -y install libblas-dev liblapack-dev
	which yum && sudo yum -y install blas-devel lapack-devel numpy-f2py

npm:               ## Install node.js/npm dependencies
	cd $(dir)/themis/web/ && npm install

publish:           ## Publish the library to PyPi
	($(VENV_RUN); ./setup.py sdist upload)

coveralls:         ## Publish coveralls metrics
	($(VENV_RUN); coveralls)

docker-build:      ## Build the Docker image
	@docker build -t $(IMAGE_NAME) .

docker-push:       ## Push image to Docker hub
	docker push $(IMAGE_NAME)

docker-run:        ## Run Themis in local Docker container
	docker run -it -p 8080:8080 -e THEMIS_DB_PASSWORD=$(THEMIS_DB_PASSWORD) -e AWS_ACCESS_KEY_ID=$(AWS_ACCESS_KEY_ID) -e AWS_SECRET_ACCESS_KEY="$(AWS_SECRET_ACCESS_KEY)" -e AWS_SESSION_TOKEN="$(AWS_SESSION_TOKEN)" -e SSH_KEY_ETL_PROD="$(SSH_KEY_ETL_PROD)" $(IMAGE_NAME) server_and_loop --port=8080

test:              ## Run tests
	($(VENV_RUN) && PYTHONPATH=$(dir)/test:$$PYTHONPATH nosetests --nocapture --no-skip --with-coverage --with-xunit --cover-package=themis test/) && \
	make lint

lint:              ## Run code linter to check code style
	($(VENV_RUN); pep8 --max-line-length=120 --ignore=E128 --exclude=web,bin,$(VENV_DIR) .)

server:            ## Start the server on port 8081
	($(VENV_RUN) && eval `ssh-agent -s` && PYTHONPATH=$(dir)/src:$$PYTHONPATH bin/themis server_and_loop --port=8081 --log=themis.log)

.PHONY: build test
