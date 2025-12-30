FROM python:3

ARG UID=1000
ARG GID=1000

WORKDIR /usr/src/app

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app .

USER ${UID}:${GID}

CMD [ "python", "./index.py" ]
