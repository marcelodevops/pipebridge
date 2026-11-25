pipeline {
    agent any
    stages {
        stage('Cycle') {
            steps {
                firstStep('seed')
            }
        }
    }
}

def firstStep(String label) {
    secondStep(label)
}

def secondStep(String label) {
    firstStep(label)
}
