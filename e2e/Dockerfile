# MCR image downloads repeatedly reset here; Playwright must match e2e/package.json.
FROM node:22-bookworm
# Fixed, world-readable browser path: tests run as the host user with HOME=/tmp.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx -y playwright@1.56.1 install --with-deps chromium && chmod -R a+rX /ms-playwright
