# Scribity tests

The Python tests cover parser behavior, server data safety, launchers, and
dashboard structure:

```sh
python3 -B -m unittest discover
```

The separate Chromium suite exercises actual dashboard interactions and save
queue/document-switch behavior:

```sh
npm install
npx playwright install chromium
npm run test:e2e
```

The browser suite serves only `dashboard.html` on a random localhost port. Its
API and JSON documents are mocked in memory; it does not start the Scribity
server, load `scribity_config.json`, or touch your working documents. The app's
React/Babel/Tailwind/Lucide CDN scripts still require an internet connection.
