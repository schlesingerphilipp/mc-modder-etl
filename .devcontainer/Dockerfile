FROM mcr.microsoft.com/devcontainers/python:3.14
WORKDIR /home/vscode/workspace
RUN pip install poetry

# opencode
RUN sudo apt update && sudo apt install nodejs npm -y
RUN npm i -g opencode-ai