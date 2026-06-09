# Google Cloud Run CI/CD Pipeline Setup Guide
## (Path A: Integrated Cloud Build / Git Continuous Deployment)

This guide provides step-by-step instructions for continuously deploying the **SweetScribbles Online Store** to Google Cloud Run directly from your GitHub repository. Whenever you push changes to the `main` branch, Google Cloud will automatically build the container image and deploy the new revision.

---

### Prerequisites
Before you start, make sure you have:
1. A **Google Cloud Platform (GCP)** account with billing enabled.
2. The **GitHub repository** (`https://github.com/Sathipoo/sweetscribbles_onlinestore.git`) pushed and up-to-date.
3. Appropriate permissions on GCP (Owner, Editor, or Cloud Run Admin + Storage Admin + Cloud Build Editor).

---

### Step 1: Navigate to Google Cloud Run
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your active project from the top dropdown.
3. In the left navigation menu (or search bar), go to **Cloud Run**.

---

### Step 2: Configure Continuous Deployment
Depending on whether you are creating a new service or configuring an existing one:

#### If creating a new service:
1. Click **Create Service** at the top.
2. Under **Deployment source**, choose:
   👉 `Continuously deploy new revisions from a source repository`
3. Click the **Set Up Cloud Build** button.

#### If updating an existing service:
1. Click on your existing Cloud Run service.
2. Click **Set Up Continuous Deployment** in the top action menu.

---

### Step 3: Connect to GitHub & Authorize
1. A panel will slide out on the right. In the **Repository provider** dropdown, select **GitHub**.
2. Click **Authenticate** (or **Manage Connections** if you need to add a new account).
3. A popup will prompt you to log in to GitHub and authorize **Google Cloud Build** to access your repositories.
4. Once authorized, select your GitHub account/organization.
5. Search for and select the repository: `Sathipoo/sweetscribbles_onlinestore`.
6. Read and agree to the terms, then click **Next**.

---

### Step 4: Configure Build Settings
1. **Branch**: Select the branch you want to deploy (e.g., `main` or `^main$`).
2. **Build Type**: Under "Build configuration", select **Dockerfile**.
3. **Source location**: Keep this as `/Dockerfile` (this matches the root-level [Dockerfile](file:///Users/sathishkumardm/Desktop/pika_work/CODE/Sweetscribbles_onlineStore/Dockerfile) we have in the workspace).
4. Click **Save**.

---

### Step 5: Configure Service Run Settings
If creating a new service, finish configuring the Cloud Run service details:
1. **Service name**: Enter a clean name (e.g., `sweetscribbles-store`).
2. **Region**: Select a region close to your target audience (e.g., `asia-south1` for Mumbai, India).
3. **CPU allocation and pricing**: Select `CPU is only allocated during request processing` to minimize cost (standard serverless model).
4. **Auto-scaling**: Set **Minimum number of instances** to `0` (scales to zero when idle to save costs) and **Maximum instances** to `10` (or safe default).
5. **Ingress**: Select **Allow all traffic** to make the store public.
6. **Authentication**: Select **Allow unauthenticated invocations** (critical for a public e-commerce storefront).

---

### Step 6: Environment Variables & Secrets (Database, etc.)
Under the **Container(s), Volumes, Connections** configuration tabs (expand **Variables & Secrets**):
1. Add any environment variables your app requires (e.g. `FLASK_ENV=production`, `ADMIN_PASSWORD`, etc.).
2. **Base URL Configuration**:
   - Add `BASE_URL`: Set this to the public URL mapped to your Cloud Run service (e.g., `https://sweetscribbles.pikachooz.com`). This is required for Zoho Payments to validate the return and notify webhooks.
3. **Database Integration**:
   - If using Cloud SQL (PostgreSQL), configure the connection string in variables: e.g., `DATABASE_URL=postgresql://<user>:<password>@<db-ip>/<db-name>`.
   - *Note*: If connecting to a local/sandbox database or external cloud instance, ensure the Cloud Run container has network permissions or a VPC connector to reach it.
4. Click **Create** or **Deploy** at the bottom.

---

### Step 7: Testing the Pipeline
Once Cloud Run completes the initial setup:
1. Go to your GitHub repository and push a change to the `main` branch.
2. In the Google Cloud Console, navigate to **Cloud Build** ➔ **History** to see your build trigger in progress.
3. Once the build completes, a green checkmark will appear, and Cloud Run will automatically deploy a new revision of the service.
4. Click the URL provided at the top of the Cloud Run dashboard to view your live site!
