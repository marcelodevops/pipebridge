#!/usr/bin/env groovy

// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: couchbase/couchbase-cli Jenkinsfile
// (branch master @ d98e187d7e4e9758a46d859393aeee84801ba75e, Apache-2.0).
// Category: Python application, Gerrit-triggered verification.

 import hudson.model.Result
 import hudson.model.Run
 import jenkins.model.CauseOfInterruption.UserInterruption

pipeline {
    agent { label "linux&&docker" }

    environment {
        VENV = "${WORKSPACE}/venv"
    }

    stages {
        stage('Run tests') {
            steps {
                sh 'python3 -m venv venv'
                sh '. venv/bin/activate && python -m pip install -e .[dev]'
                sh '. venv/bin/activate && python -m pytest tests/ -v'
            }
        }

        stage('Lint') {
            steps {
                sh '. venv/bin/activate && python -m pylint bin/*'
            }
        }
    }

    post {
        success {
            echo 'verification passed'
        }
        failure {
            echo 'verification failed'
        }
    }
}
