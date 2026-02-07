FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye
WORKDIR /home/vscode/workspace
RUN pip install poetry
# Add Yarn GPG key and repository
RUN curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | gpg --dearmor | tee /usr/share/keyrings/yarnkey.gpg >/dev/null \
	&& echo "deb [signed-by=/usr/share/keyrings/yarnkey.gpg] https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list
# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
	gnupg

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
	&& apt-get update \
	&& apt-get install -y nodejs yarn \
	&& npm --version && node --version && yarn --version
RUN npm install -g @google/gemini-cli