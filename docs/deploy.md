# Hosted demo

A public demo runs the web app with **synthetic data only**. Never connect a client system to it.

## Render (free plan)

`render.yaml` describes the service. To create it:

1. Sign in at [render.com](https://render.com) with your GitHub account.
2. Choose **New > Blueprint**, pick the `testbench` repository and confirm. Render builds the `Dockerfile` and generates three secrets: `TESTBENCH_SECRET_KEY` and the two demo passwords.
3. When the deploy is live, open the service URL (`https://testbench-demo-….onrender.com`). Read the demo passwords under **Environment** in the Render dashboard:
   - `consultant@nmbs-demo.test` uses `TESTBENCH_DEMO_PASSWORD_NMBS`
   - `consultant@other-demo.test` uses `TESTBENCH_DEMO_PASSWORD_OTHER`

Every push to the deployed branch redeploys the demo.

Limits of the free plan: the service sleeps after about 15 minutes without visits, so the first visit afterwards takes up to a minute. The disk is not persistent, so the demo is re-seeded on each start and earlier runs disappear. That is acceptable for a demo; a pilot with a client needs a paid plan with a persistent disk, or another host.

## Any other Docker host

```bash
docker build -t testbench .
docker run -p 8000:8000 \
  -e TESTBENCH_SECRET_KEY=... \
  -e TESTBENCH_DEMO_PASSWORD_NMBS=... -e TESTBENCH_DEMO_PASSWORD_OTHER=... \
  -v testbench-data:/data testbench
```

Serve it behind HTTPS: session cookies are marked `Secure`, so sign-in does not work over plain HTTP.
