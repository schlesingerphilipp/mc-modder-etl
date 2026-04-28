FROM mcr.microsoft.com/devcontainers/python:3.13
WORKDIR /home/vscode/workspace
RUN pip install poetry graphifyy==0.5.0

# opencode
RUN sudo apt update && sudo apt install nodejs npm -y
RUN npm i -g opencode-ai@1.14.18