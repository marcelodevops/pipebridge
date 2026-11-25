pipeline {
    agent any
    stages {
        stage('Deploy') {
            steps {
                runUnsupportedHelper('prod')
            }
        }
    }
}

def runUnsupportedHelper(String envName) {
    script {
        sh "echo deploying ${envName}"
    }
}
