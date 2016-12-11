FROM python:2

MAINTAINER Waldemar Hummer (whummer@atlassian.com)

# create workdir
RUN mkdir -p /opt/code/themis
WORKDIR /opt/code/themis/

# install build tools
RUN apt-get update && apt-get install -y gcc git make npm && apt-get clean

# install Themis package
RUN pip install themis-autoscaler

# Copy themis files from local copy
ADD requirements.txt /opt/code/themis/requirements.txt
RUN pip install -r requirements.txt
ADD bin /opt/code/themis/bin
ADD themis /opt/code/themis/themis
RUN rm -f /usr/local/bin/themis && ln -s /opt/code/themis/bin/themis /usr/local/bin/themis

# Set PYTHONPATH
ENV PYTHONPATH /opt/code/themis

# make sure we have write access to workdir
RUN chmod 777 /opt/code/themis/

# assign random user id
# TODO: we currently can't use "random" uid because then ssh commands fail
# USER 24624336
# ENV USER docker

# expose service port
EXPOSE 8080

# set default env variables
ENV AWS_DEFAULT_REGION us-east-1

# TODO: uncomment this for testing only
# ADD themis.config.json /opt/code/themis/themis.config.json
# ADD themis.resources.json /opt/code/themis/themis.resources.json

# define command
ENTRYPOINT ["themis"]
