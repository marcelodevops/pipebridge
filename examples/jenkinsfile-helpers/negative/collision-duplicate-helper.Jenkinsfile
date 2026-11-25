pipeline {
    agent any
    stages {
        stage('Deploy') {
            steps {
                deploy('staging')
            }
        }
    }
}

def deploy(String target) {
    sh "printf '%s' \"${target}\""
}

def deploy(String target) {
    echo "duplicate ${target}"
}
