String GLOBAL_ENV = 'prod'

pipeline {
    agent any
    stages {
        stage('Deploy') {
            steps {
                deployWithCapturedVar('v1.0.0')
            }
        }
    }
}

def deployWithCapturedVar(String version) {
    sh "printf '%s:%s\n' \"${GLOBAL_ENV}\" \"${version}\""
}
