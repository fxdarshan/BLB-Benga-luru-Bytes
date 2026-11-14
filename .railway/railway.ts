// Railway configuration for the BLB API, as code. It replaces railway.json, which Railway stopped
// reading. Railway never reads this file during a deploy: preview a change with
// `npx railway config plan`, then apply it with `npx railway config apply`.
//
// Variables, including the Groq key, stay in Railway's dashboard. IaC never reads or writes them.
// See https://docs.railway.com/infrastructure-as-code
import { defineRailway, github, project, service } from "railway/iac";

// This repository manages only its own resources in the project.
export const partial = "BLB-Benga-luru-Bytes";

export default defineRailway(() => {
  const api = service("BLB-Benga-luru-Bytes", {
    // checkSuites: wait for the commit's GitHub checks (the CI workflow) to pass before deploying.
    source: github("fxdarshan/BLB-Benga-luru-Bytes", { branch: "main", checkSuites: true }),
    build: {
      buildEnvironment: "V3",
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile",
      // Only changes to the files the image is built from redeploy the API, so frontend and docs
      // commits don't restart it.
      watchPatterns: [
        "src/**",
        "pyproject.toml",
        "uv.lock",
        "Dockerfile",
        ".dockerignore",
        "Doc/problemStatement.md",
      ],
    },
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 3 },
    // Traffic moves to a new deployment only once /health answers 200.
    healthcheck: "/health",
    healthcheckTimeout: 120,
    replicas: { iad: 1 },
    networking: { privateNetworkEndpoint: "blb-benga-luru-bytes" },
  });

  return project("fearless-dedication", {
    variables: { managed: false },
    resources: [api],
  });
});
