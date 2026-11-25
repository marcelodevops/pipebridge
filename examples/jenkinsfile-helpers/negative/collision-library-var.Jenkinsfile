@Library('build-lib') _
pipeline {
    agent any
    stages {
        stage('Publish') {
            steps {
                publish('packaged')
            }
        }
    }
}

def publish(String label) {
    sh "printf '%s' \"${label}\""
}
