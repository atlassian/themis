# Themis - AWS EMR Autoscaler

== Installation

Below is a (probably incomplete) list of steps required to install and run the autoscaling tool.

sudo yum -y install blas-devel lapack-devel numpy-f2py
git clone ssh://git@stash.atlassian.com:7997/data/socrates-bootstrap.git
cd socrates-bootstrap/environment-scripts
sudo yum install nodejs npm --enablerepo=epel
vi ~/.ssh/ai-etl.pem 			# enter private key
chmod 600 ~/.ssh/ai-etl.pem
vi ~/.ssh/atl-ai-etl-dev.pem 	# enter private key
chmod 600 ~/.ssh/atl-ai-etl-dev.pem
aws configure 					# enter AWS credentials ...
eval `ssh-agent -s`

./scaling build
./scaling.py server_and_loop -p 8081
