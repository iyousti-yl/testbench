# Hosted instance

The web app can run on any Docker host. Until a pilot is agreed, connect **synthetic or sandbox data only**: never a client's production tenant.

## Render (free plan)

`render.yaml` describes the service. To create it:

1. Sign in at [render.com](https://render.com) with your GitHub account.
2. Choose **New > Blueprint**, pick the `testbench` repository and confirm. Render builds the `Dockerfile`, generates `TESTBENCH_SECRET_KEY` and asks for `TESTBENCH_ADMIN_EMAIL` and `TESTBENCH_ADMIN_PASSWORD` (at least 12 characters).
3. When the deploy is live, open the service URL (`https://testbench-….onrender.com`) and sign in with that email and password. On every start the app creates this account if it does not exist yet.

Every push to the deployed branch redeploys the service.

Limits of the free plan: the service sleeps after about 15 minutes without visits, so the first visit afterwards takes up to a minute. The disk is not persistent, so workspaces, connections and runs disappear on each restart. That is acceptable for a try-out; a pilot with a client needs a paid plan with a persistent disk, or another host.

## Any other Docker host

```bash
docker build -t testbench .
docker run -p 8000:8000 \
  -e TESTBENCH_SECRET_KEY=... \
  -e TESTBENCH_ADMIN_EMAIL=you@example.com -e TESTBENCH_ADMIN_PASSWORD=... \
  -v testbench-data:/data testbench
```

Serve it behind HTTPS: session cookies are marked `Secure`, so sign-in does not work over plain HTTP.
