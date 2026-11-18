// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: superstreamlabs/memphis Jenkinsfile
// (branch master @ 0f97a13117ec04fa914c3c539e81a9a4145cec7a, BSL 1.1).
// Category: container build/publish + Kubernetes (k3s) deployment test.
String unique_id = "a1b2"
pipeline {
  environment {
      versionTag = readFile('./version.conf')
      gitBranch = "${env.BRANCH_NAME}"
      imageName = "app"
      repoUrlPrefix = "example"
  }

  agent {
    label 'big-fleet'
  }

  stages {
    stage('Pre Build') {
      steps {
        script {
          sh "make set-build-git-remote"
          sh "make set-version"
        }
      }
    }

    stage('Build') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'docker-hub',
          usernameVariable: 'DOCKER_HUB_CREDS_USR',
          passwordVariable: 'DOCKER_HUB_CREDS_PSW')]) {
          sh 'echo "$DOCKER_HUB_CREDS_PSW" | docker login -u "$DOCKER_HUB_CREDS_USR" --password-stdin'
          sh "docker build -t ${repoUrlPrefix}/${imageName}:${versionTag} ."
          sh "docker push ${repoUrlPrefix}/${imageName}:${versionTag}"
        }
      }
    }

    stage('Deploy test env') {
      steps {
        sh "kubectl config use-context k3s"
        sh "kubectl create namespace app-${unique_id} --dry-run=client -o yaml | kubectl apply -f -"
        sh "kubectl apply -f deploy/ -n app-${unique_id}"
      }
    }
  }

  post {
    success {
      notifySuccessful()
    }

    failure {
      notifyFailed()
    }
  }
}

def notifySuccessful() {
  echo 'success'
}

def notifyFailed() {
  echo 'failure'
}
