FROM telegraf:1.17

WORKDIR /

RUN apt-get update \
    && apt-get install -y python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /
RUN pip3 install -r requirements.txt

COPY bin/tsds-output.py /usr/bin/
COPY conf/dummy.conf /etc/telegraf/telegraf.conf

ENTRYPOINT [ "/usr/bin/telegraf"]
CMD [ "-config", "/etc/telegraf/telegraf.conf", "-config-directory", "/etc/telegraf/conf.d" ]