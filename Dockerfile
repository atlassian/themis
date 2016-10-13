FROM python:2-onbuild

MAINTAINER Waldemar Hummer (whummer@atlassian.com)

# create workdir
RUN mkdir -p /opt/code/themis
WORKDIR /opt/code/themis/

# install build tools
RUN apt-get update && apt-get install -y gcc git make npm && apt-get clean

# install Themis package
RUN pip install themis-autoscaler

# make sure we have write access to workdir
RUN chmod 777 -R /opt/code/themis/

# assign random user id
USER 24624336
ENV USER docker

# expose service port
EXPOSE 8080

# set default env variables
ENV AWS_DEFAULT_REGION us-east-1

# define command
CMD ["themis", "server_and_loop", "--port=8080", "--log=themis.log"]
