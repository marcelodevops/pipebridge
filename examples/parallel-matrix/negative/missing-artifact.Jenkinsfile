pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'echo "building"'
            }
        }
        stage('Test') {
            steps {
                unstash 'nonexistent-bin'
                sh 'echo "testing"'
            }
        }
    }
}
