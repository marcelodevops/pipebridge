// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: jetty/jetty.project Jenkinsfile
// (branch jetty-12.1.x @ 1ba887ccc5fa3a5fa8a512b7deacc0fff02f0a87, EPL-2.0/
// Apache-2.0 dual license). Category: Java/Maven, parallel matrix build.
pipeline {
  agent none
  options {
    skipDefaultCheckout()
    durabilityHint('PERFORMANCE_OPTIMIZED')
    disableRestartFromStage()
    disableConcurrentBuilds(abortPrevious: true)
  }
  stages {
    stage("Parallel Stage") {
      parallel {
        stage("Build / Test - JDK21") {
          agent { node { label 'linux-dind' } }
          when { beforeAgent true; expression { isReleaseLine() } }
          steps {
            timeout( time: 210, unit: 'MINUTES' ) {
              script {
                properties([buildDiscarder(logRotator(numToKeepStr: '60'))])
              }
              checkout scm
              mavenBuild("jdk21", "clean install")
            }
          }
        }
        stage("Build / Test - JDK25") {
          agent { node { label 'linux-dind' } }
          when { beforeAgent true; expression { isReleaseLine() } }
          steps {
            timeout( time: 210, unit: 'MINUTES' ) {
              mavenBuild("jdk25", "clean install")
            }
          }
        }
      }
    }
  }
  post {
    always {
      junit allowEmptyResults: true, testResults: '**/target/surefire-reports/*.xml'
    }
    success {
      websiteBuild()
    }
    failure {
      websiteBuild()
    }
  }
}

def slackNotif() {
  script {
    if (env.BRANCH_NAME == 'main') {
      echo 'notifying'
    }
  }
}

def mavenBuild(jdk, cmdline) {
  echo "maven build ${jdk}: ${cmdline}"
}

def websiteBuild() {
  echo 'website build'
}
