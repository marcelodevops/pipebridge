#!/usr/bin/env groovy

// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: hmrc/api-platform-get-apis-lambda Jenkinsfile
// (branch main @ f2276abf85d7c174b1a20cf80d4155b8a82722e5, Apache-2.0).
// Category: infrastructure deployment (per-stage dockerfile agents, stash).

// Not using the JOB_BASE_NAME env variable as the pr builder name would be incorrect for example PR-30
String full_job_name = "${env.JOB_NAME?.split('/')[1]}"

// Assume that the zip artefact has the same name as the Jenkins job
String target_file = "${full_job_name}.zip"

pipeline {
    agent { label 'docker' }

    environment {
        GIT_ID = "${sh(returnStdout: true, script: 'git describe --always').trim()}"
        BUILD_TIME = new Date().format('yyyyMMddHHmmss')
        ALIAS = "${GIT_ID}-${BUILD_TIME}"
    }

    stages {
        stage('Set build details') {
            steps {
                script {
                    currentBuild.description = "version - ${ALIAS}"
                }
            }
        }
        stage('Build artefact') {
            agent {
                dockerfile {
                    // Cache dependencies
                    args "-v /tmp/.cache:/root/.cache -u root:root"
                }
            }
            steps {
                sh(script: "sbt assembly")
                stash(
                    name: 'artefact',
                    includes: target_file
                )
            }
        }
        stage('Run tests') {
            agent {
                dockerfile {
                    args "-v /tmp/.cache:/root/.cache -u root:root"
                }
            }
            steps {
                sh(script: "sbt test")
            }
        }
        stage('Generate sha256') {
            when {
                expression {
                    env.GIT_BRANCH == 'main'
                }
            }
            steps {
                unstash(name: 'artefact')
                sh("openssl dgst -sha256 -binary ${target_file} | openssl enc -base64 > ${full_job_name}.zip.base64sha256")
            }
        }
        stage('Deploy') {
            agent {
                dockerfile {
                    args "-v /tmp/.cache:/root/.cache -u root:root"
                }
            }
            steps {
                sh("./deploy.sh ${ALIAS}")
            }
        }
    }

    post {
        always {
            echo "build ${currentBuild.currentResult}"
        }
    }
}
