FROM ubuntu

# Update the repository sources list
RUN apt-get update
# Install python-pip
RUN apt-get install -y python
RUN apt-get install -y python-pip
RUN apt-get install -y libpq-dev python-dev
RUN apt-get install -y java-common
RUN apt install -y default-jre
RUN apt install -y openjdk-8-jre-headless

# move files to dir
COPY . /app
WORKDIR /app

RUN pip install -r requirements.txt

ENTRYPOINT ["python2", "-u", "grid_listener.py"]
CMD []