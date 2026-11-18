// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: kymatio/kymatio Jenkinsfile
// (branch main @ 50d7461db6111eb4b20d32e670a5556d4da6134f, BSD-3-Clause).
// Category: Python application, GPU container build + test.
// NOTE: the original embeds a hardcoded codecov upload token in shell text;
// the equivalent deliberately uses an environment-variable reference instead.
pipeline {
  agent none
  options {
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '8', daysToKeepStr: '20'))
    timeout(time: 1, unit: 'HOURS')
  }
  stages {
    stage('main') {
      agent {
        dockerfile {
          dir 'tools'
          args '--gpus 1'
        }
      }
      environment {
        HOME = "$WORKSPACE/build"
      }
      steps {
        sh 'python3 -m pip --version'
        sh 'python3 -m venv --system-site-packages --without-pip $HOME'
        sh '''#!/bin/bash -ex
          source $HOME/bin/activate
          python3 setup.py develop
          TF_FORCE_GPU_ALLOW_GROWTH=true python3 -m pytest --cov=kymatio
          python3 -m coverage xml
        '''
      }
    }
  }
  post {
    failure {
      mail to: 'team@example.org', subject: 'build failed'
    }
  }
}
