pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'echo built-in step'
            }
        }
    }
}

def sh(String cmd) {
    echo "shadowed ${cmd}"
}
