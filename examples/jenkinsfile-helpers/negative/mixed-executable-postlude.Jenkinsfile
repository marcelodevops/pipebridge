pipeline {
    agent any
    stages {
        stage('Test') {
            steps {
                runSuite('unit')
            }
        }
    }
}

def runSuite(String suite) {
    sh "pytest -k \"${suite}\""
}

def unusedHelper() {
    echo 'never called'
}

println 'postlude side effect'
