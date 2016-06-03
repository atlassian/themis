# Themis - Autoscaling EMR Clusters on AWS

Themis is an autoscaler for Elastic Map Reduce (EMR) clusters on Amazon Web Services.

Themis in Greek mythology is the goddess of divine order, justice, and fairness, just like
the Themis autoscaler whose job is to continuously maintain a tradeoff between costs and
performance.

![Themis](https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/Justitia%2C_Jost_Amman.png/200px-Justitia%2C_Jost_Amman.png)

## Background

Elastic Map Reduce (EMR) is a managed Hadoop environment for Big Data analytics offered by Amazon Web Services (AWS).
The architecture of EMR clusters is built for scalability, with a single master node and multiple worker nodes that
can be dynamically added and removed via Amazon's API.

Due to different usage patterns (e.g., high load during work hours, no load over night), the cluster may become either
underprovisioned (users experience bad performance) or overprovisioned (cluster is idle, causing a waste of resources
and unnecessary costs).

However, while autoscaling has become state-of-the-art for applications in Amazon's Elastic Compute Cloud (EC2),
currently there exists no out-of-the-box solution for autoscaling analytics clusters on EMR.

The "Themis" autoscaling tool actively monitors the performance of a user's EMR clusters and automatically scales the
cluster up and down where appropriate. A Web user interface (UI) is available to display the key data. Themis supports
both, reactive and proactive autoscaling. The rules for autoscaling can be customized in a configuration file or via
the Web UI.

## Requirements

* `make`
* `python`
* `pip` (python package manager)
* `npm` (node.js package manager, needed for Web UI dependencies)

## Installation

To install the tool, run the following command:

```
make build
```

This will install the required pip dependencies in your local system (e.g., in 
`/usr/local/lib/python2.7/site-packages/`), as well as the node modules for the
Web UI in `./web/node_modules/`. Depending in your system, some pip/npm modules may require
additional native libs installed. Under Redhat/CentOS or Amazon Linux, you may first need to
run the following command:

```
sudo yum -y install blas-devel lapack-devel numpy-f2py
```

## Testing

The project comes with a set of unit and integration tests which can be kicked off via a make
target:

```
make test
```

The set of tests is currently rather small, but we seek to improve the test coverage as the
tool evolves.

## Configuration

Themis autoscaler relies on the `aws` command line interface (AWS CLI) to be installed and
configured with your AWS account credentials. If you have not yet done so, run this command and
follow the instructions:

```
aws configure
```

For the configuration of the autoscaler itself, there are a number of settings that you can
configure directly in the Web UI (see below).

## Running

The Makefile contains a target to conveniently run the server application. Prior to that, make
sure that ssh agent forwarding is enabled in the shell that executes the server.

```
# enable ssh agent forwarding
eval `ssh-agent -s`
# start the server on port 9090
make server
```

## License

Themis is released under the Apache License, Version 2.0 (see LICENSE.txt).

We build on a number of third-party software tools, with the following licenses:

Third-Party software		| 	License
----------------------------|-----------------------
**Python/pip modules:**		|
awscli						|	Apache License 2.0
coverage 					|	Apache License 2.0
cssselect	  				|	BSD License
docopt						|	MIT License
flask						|	BSD License
flask-swagger				|	MIT License
nose						|	GNU LGPL
pyhive						|	Apache License 2.0
scipy						|	BSD License
**Node.js/npm modules:**	|
swagger-client				|	Apache License 2.0
jquery						|	MIT License
angular-tablesort			|	MIT License
almond						|	MIT License
angular						|	MIT License
angular-ui-router			|	MIT License
angular-resource			|	MIT License
angular-sanitize			|	MIT License
showdown					|	BSD 3-Clause License
angular-aui					|	Atlassian Design Guidelines License
